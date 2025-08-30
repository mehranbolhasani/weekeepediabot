import logging
import os
import urllib.parse
import requests
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import wikipedia

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Get bot token from environment variable
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

class WikipediaBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Set up command and message handlers."""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "🔍 **Welcome to Wikipedia Bot!**\n\n"
            "📚 Just send me any topic and I'll find the Wikipedia article for you!\n\n"
            "✨ **Examples:**\n"
            "• Pink Floyd\n"
            "• Artificial Intelligence\n"
            "• Python programming\n"
            "• Albert Einstein",
            parse_mode='Markdown'
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages."""
        query = update.message.text.strip()
        if query:
            await self.get_article(update.message, query)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        
        if callback_data.startswith("wiki_"):
            # Extract the article title from callback data
            encoded_title = callback_data[5:]  # Remove "wiki_" prefix
            title = urllib.parse.unquote(encoded_title)
            await self.get_article(query.message, title)
        elif callback_data.startswith("full_"):
            # Handle full article request
            encoded_title = callback_data[5:]  # Remove "full_" prefix
            title = urllib.parse.unquote(encoded_title)
            await self.send_full_article(query.message, title)
        elif callback_data.startswith("longer_"):
            # Handle longer summary request
            encoded_title = callback_data[7:]  # Remove "longer_" prefix
            title = urllib.parse.unquote(encoded_title)
            await self.send_longer_summary(query.message, title)

    async def get_wikipedia_page_direct(self, title):
        """Direct Wikipedia API call to bypass library issues"""
        try:
            # Step 1: Search for the page using opensearch API (more reliable)
            search_url = "https://en.wikipedia.org/w/api.php"
            search_params = {
                'action': 'opensearch',
                'search': title,
                'limit': 10,
                'format': 'json'
            }
            
            print(f"🔍 Direct API search for: '{title}'")
            search_response = requests.get(search_url, params=search_params, timeout=10)
            search_data = search_response.json()
            
            if len(search_data) < 2 or not search_data[1]:
                return None
                
            # Step 2: Smart page selection
            page_titles = search_data[1]
            print(f"📋 Direct API found pages: {page_titles}")
            
            # AI-powered page selection
            def score_page_title(page_title, search_term):
                title_lower = page_title.lower()
                search_lower = search_term.lower()
                score = 0
                
                # Exact match gets highest priority
                if title_lower == search_lower:
                    score += 100
                elif search_lower in title_lower:
                    score += 50
                
                # Heavy penalties for sub-topics
                penalties = {
                    'album': -60, 'song': -60, 'single': -60,
                    'discography': -70, 'tour': -50, 'live': -50,
                    'compilation': -40, 'greatest hits': -40
                }
                
                for keyword, penalty in penalties.items():
                    if keyword in title_lower:
                        score += penalty
                
                # Penalty for separators indicating sub-topics
                if any(sep in page_title for sep in [' – ', ' - ', ': ', '(album)', '(song)']):
                    if '(band)' in page_title or '(musician)' in page_title:
                        score += 20  # Actually prefer these for artists
                    else:
                        score -= 30
                
                # Bonus for shorter titles (main topics)
                if len(page_title) < 15:
                    score += 15
                elif len(page_title) > 30:
                    score -= 10
                
                return score
            
            # Score and select best page
            scored_pages = [(score_page_title(title, title), title) for title in page_titles]
            scored_pages.sort(key=lambda x: x[0], reverse=True)
            
            print(f"🤖 AI scoring: {[(title, score) for score, title in scored_pages[:3]]}")
            
            best_page_title = scored_pages[0][1]
            print(f"✅ Selected page: '{best_page_title}'")
            
            # Step 3: Get page content
            content_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(best_page_title)}"
            content_response = requests.get(content_url, timeout=10)
            content_data = content_response.json()
            
            return {
                'title': content_data.get('title', best_page_title),
                'summary': content_data.get('extract', ''),
                'url': content_data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                'image': content_data.get('thumbnail', {}).get('source', '') if content_data.get('thumbnail') else ''
            }
            
        except Exception as e:
            print(f"❌ Direct API failed: {e}")
            return None

    async def get_article(self, message, title):
        """Fetch and send Wikipedia article summary."""
        try:
            print(f"🔍 Attempting to load page: '{title}'")
            
            # First try direct Wikipedia API (bypasses library issues)
            direct_result = await self.get_wikipedia_page_direct(title)
            if direct_result:
                print(f"✅ Direct API success: {direct_result['title']}")
                await self.send_direct_summary(message, direct_result)
                return
            
            # Fallback to original library method with smart prioritization
            page = None
            try:
                page = wikipedia.page(title, auto_suggest=True)
                print(f"✅ Library success: {page.title}")
            except wikipedia.exceptions.DisambiguationError as e:
                print(f"🔀 Disambiguation found, trying first option: {e.options[0]}")
                page = wikipedia.page(e.options[0])
            except wikipedia.exceptions.PageError:
                print(f"❌ Library failed, trying search approach")
                try:
                    search_results = wikipedia.search(title, results=8)
                    print(f"🔍 Search found: {search_results}")
                    
                    # Apply AI scoring to library search results
                    def score_library_result(result, search_term):
                        result_lower = result.lower()
                        search_lower = search_term.lower()
                        score = 0
                        
                        # Exact match gets highest priority
                        if result_lower == search_lower:
                            score += 100
                        elif search_lower in result_lower:
                            score += 50
                        
                        # Heavy penalties for sub-topics
                        penalties = {
                            'album': -50, 'song': -50, 'single': -50,
                            'discography': -60, 'tour': -40, 'live': -40,
                            'compilation': -30, 'greatest hits': -30
                        }
                        
                        for keyword, penalty in penalties.items():
                            if keyword in result_lower:
                                score += penalty
                        
                        # Penalty for parentheses (usually indicates sub-topics)
                        if '(' in result and ')' in result:
                            if '(band)' in result_lower or '(musician)' in result_lower:
                                score += 20  # Actually prefer these for artists
                            else:
                                score -= 25
                        
                        # Bonus for shorter titles (main topics)
                        if len(result) < 15:
                            score += 15
                        elif len(result) > 30:
                            score -= 10
                        
                        return score
                    
                    # Score and sort results
                    scored_results = [(score_library_result(r, title), r) for r in search_results]
                    scored_results.sort(key=lambda x: x[0], reverse=True)
                    
                    print(f"🤖 Library AI scoring: {[(r, score) for score, r in scored_results[:3]]}")
                    
                    # Try results in scored order
                    for score, result in scored_results:
                        try:
                            page = wikipedia.page(result, auto_suggest=True)
                            print(f"✅ Search success: {result} (score: {score}) -> {page.title}")
                            break
                        except Exception:
                            continue
                except Exception:
                    pass
            
            if page:
                await self.send_article_summary(message, page)
            else:
                await self.handle_page_not_found(message, title)
                
        except Exception as e:
            print(f"❌ Error in get_article: {e}")
            await message.reply_text(
                f"🤔 **Sorry, something went wrong while searching for '{title}'**\n\n💡 **Please try again or search for something else!**",
                parse_mode='Markdown'
            )

    async def send_direct_summary(self, message, page_data):
        """Send summary from direct API result"""
        try:
            title = page_data['title']
            summary = page_data['summary']
            url = page_data['url']
            image_url = page_data['image']
            
            # Create enhanced summary
            if len(summary) > 800:
                summary = summary[:800] + "..."
            
            # Format the message
            formatted_text = f"📖 **{title}**\n\n"
            formatted_text += f"_{summary}_\n\n"
            formatted_text += f"🔗 [Read full article on Wikipedia]({url})"
            
            # Create inline keyboard
            encoded_title = urllib.parse.quote(title)
            keyboard = [
                [InlineKeyboardButton("📖 Full Article", url=url)],
                [InlineKeyboardButton("🔍 Search Again", callback_data=f"search_again")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send image if available
            if image_url:
                try:
                    await message.reply_photo(
                        photo=image_url,
                        caption=formatted_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    return
                except Exception:
                    pass  # Fallback to text message
            
            # Send text message
            await message.reply_text(
                formatted_text,
                reply_markup=reply_markup,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
        except Exception as e:
            print(f"❌ Error sending direct summary: {e}")
            await message.reply_text(
                f"🤔 **Found the article but couldn't format it properly**\n\n🔗 [View on Wikipedia]({page_data.get('url', '')})",
                parse_mode='Markdown'
            )

    async def send_article_summary(self, message, page):
        """Send Wikipedia article summary with enhanced formatting."""
        try:
            # Get featured image
            image_url = await self.get_featured_image(page)
            
            # Create enhanced summary
            summary_text, _ = await self.create_enhanced_summary(page)
            
            # Create inline keyboard for more options
            encoded_title = urllib.parse.quote(page.title)
            keyboard = [
                [InlineKeyboardButton("📖 Read Full Article", url=page.url)],
                [InlineKeyboardButton("📝 Longer Summary", callback_data=f"longer_{encoded_title}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send with image if available
            if image_url:
                try:
                    await message.reply_photo(
                        photo=image_url,
                        caption=summary_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                    return
                except Exception as e:
                    print(f"Failed to send image: {e}")
            
            # Send text message if image fails or not available
            await message.reply_text(
                summary_text,
                reply_markup=reply_markup,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            
        except Exception as e:
            print(f"Error sending summary: {e}")
            await message.reply_text(
                f"🤔 **Found the article but couldn't format it properly**\n\n🔗 [View on Wikipedia]({page.url})",
                parse_mode='Markdown'
            )

    async def get_featured_image(self, page):
        """Extract the main/featured image from Wikipedia page."""
        try:
            images = page.images
            if not images:
                return None
            
            # Filter out common non-content images
            excluded_patterns = [
                'commons-logo', 'wikimedia', 'edit-icon', 'wiki.png',
                'folder', 'audio', 'speaker', 'sound', '.ogg', '.wav',
                'disambiguation', 'stub', 'ambox', 'question_book'
            ]
            
            for image_url in images[:10]:  # Check first 10 images
                image_lower = image_url.lower()
                if any(pattern in image_lower for pattern in excluded_patterns):
                    continue
                
                # Prefer larger images (likely main content)
                if any(size in image_lower for size in ['300px', '250px', '200px']):
                    return image_url
                
                # Return first valid image if no sized ones found
                if image_url.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    return image_url
            
            return None
        except Exception:
            return None

    async def create_enhanced_summary(self, page):
        """Create an enhanced, well-formatted summary."""
        try:
            # Get the summary (first few sentences)
            summary = wikipedia.summary(page.title, sentences=6)
            
            # Clean up the summary
            summary = summary.replace('\n', ' ').strip()
            
            # Format the title and summary
            title = page.title
            formatted_text = f"📖 **{title}**\n\n"
            
            # Add italics to first sentence for emphasis
            sentences = summary.split('. ')
            if sentences:
                first_sentence = sentences[0] + '.'
                rest_summary = '. '.join(sentences[1:]) if len(sentences) > 1 else ''
                formatted_text += f"_{first_sentence}_\n\n"
                if rest_summary:
                    formatted_text += f"{rest_summary}\n\n"
            else:
                formatted_text += f"_{summary}_\n\n"
            
            # Add Wikipedia link
            formatted_text += f"🔗 [Read more on Wikipedia]({page.url})"
            
            return formatted_text, None
            
        except Exception as e:
            print(f"Error creating summary: {e}")
            return f"📖 **{page.title}**\n\n🔗 [View on Wikipedia]({page.url})", None

    async def send_longer_summary(self, message, title):
        """Send a longer, more detailed summary."""
        try:
            page = wikipedia.page(title, auto_suggest=True)
            longer_summary = wikipedia.summary(title, sentences=10)
            
            # Format longer summary
            formatted_text = f"📖 **{page.title}** _(Detailed Summary)_\n\n"
            formatted_text += f"{longer_summary}\n\n"
            formatted_text += f"🔗 [Read full article on Wikipedia]({page.url})"
            
            # Split into chunks if too long
            chunks = self.split_text(formatted_text)
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:  # Last chunk gets the keyboard
                    keyboard = [[InlineKeyboardButton("📖 Read Full Article", url=page.url)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await message.reply_text(chunk, reply_markup=reply_markup, parse_mode='Markdown')
                else:
                    await message.reply_text(chunk, parse_mode='Markdown')
                    
        except Exception as e:
            print(f"Error sending longer summary: {e}")
            await message.reply_text(
                f"🤔 **Couldn't load detailed summary for '{title}'**\n\n💡 **Try the regular search instead!**",
                parse_mode='Markdown'
            )

    async def send_full_article(self, message, title):
        """Send the full Wikipedia article in chunks."""
        try:
            page = wikipedia.page(title, auto_suggest=True)
            content = page.content
            
            # Format full article
            formatted_text = f"📖 **{page.title}** _(Full Article)_\n\n{content}"
            
            # Split into chunks
            chunks = self.split_text(formatted_text, max_length=3000)
            
            for i, chunk in enumerate(chunks):
                if i == 0:  # First chunk
                    await message.reply_text(f"📚 **Full Article** (Part {i+1}/{len(chunks)})\n\n{chunk}", parse_mode='Markdown')
                elif i == len(chunks) - 1:  # Last chunk gets the link
                    keyboard = [[InlineKeyboardButton("🔗 View on Wikipedia", url=page.url)]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await message.reply_text(f"📚 **Part {i+1}/{len(chunks)}**\n\n{chunk}", reply_markup=reply_markup, parse_mode='Markdown')
                else:  # Middle chunks
                    await message.reply_text(f"📚 **Part {i+1}/{len(chunks)}**\n\n{chunk}", parse_mode='Markdown')
                    
        except Exception as e:
            print(f"Error sending full article: {e}")
            await message.reply_text(
                f"🤔 **Couldn't load full article for '{title}'**\n\n💡 **Try viewing it directly on Wikipedia!**",
                parse_mode='Markdown'
            )

    def split_text(self, text, max_length=4000):
        """Split text into chunks that fit Telegram's message limit."""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        current_chunk = ""
        
        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) + 2 <= max_length:
                if current_chunk:
                    current_chunk += '\n\n' + paragraph
                else:
                    current_chunk = paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = paragraph
                else:
                    # Paragraph is too long, split by sentences
                    sentences = paragraph.split('. ')
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) + 2 <= max_length:
                            if current_chunk:
                                current_chunk += '. ' + sentence
                            else:
                                current_chunk = sentence
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks

    async def handle_page_not_found(self, message, title):
        """Handle cases where no Wikipedia page is found."""
        try:
            # Try to find similar articles
            search_results = wikipedia.search(title, results=8)
            # Filter out the failed title to avoid infinite loops
            filtered_results = [result for result in search_results if result.lower() != title.lower()]
            
            if filtered_results:
                keyboard = []
                for result in filtered_results[:3]:  # Show top 3 suggestions
                    encoded_result = urllib.parse.quote(result)
                    keyboard.append([InlineKeyboardButton(result, callback_data=f"wiki_{encoded_result}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text(
                    f"🤔 **Couldn't find '{title}'**\n\n💡 **Did you mean one of these instead?**",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await message.reply_text(
                    f"🤔 **Couldn't find '{title}'**\n\n💡 **Try:**\n• Being more specific\n• Using the full name\n• Checking your spelling\n• Searching for a related topic",
                    parse_mode='Markdown'
                )
        except Exception:
            await message.reply_text(
                f"🤔 **Couldn't find '{title}'**\n\n💡 **Try searching for something else!**",
                parse_mode='Markdown'
            )

    def run(self):
        """Start the bot."""
        print("🤖 Wikipedia Bot is starting...")
        self.application.run_polling()

if __name__ == "__main__":
    bot = WikipediaBot()
    bot.run()
