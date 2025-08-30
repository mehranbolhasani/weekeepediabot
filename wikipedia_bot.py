import logging
import os
import wikipedia
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Get bot token from environment variable
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it in Railway.")

# Set Wikipedia language (optional)
wikipedia.set_lang("en")

class WikipediaBot:
    def __init__(self):
        self.max_message_length = 4096  # Telegram's message limit
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /start is issued."""
        welcome_text = """
🔍 **Wikipedia Search Bot**

Send me any topic and I'll search Wikipedia for you!

Commands:
• Just type your search query
• /help - Show this help message

Examples:
• "Albert Einstein"
• "Python programming"
• "Solar system"
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /help is issued."""
        await self.start(update, context)

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
                current_chunk += paragraph + '\n\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = paragraph + '\n\n'
                else:
                    # If single paragraph is too long, split by sentences
                    sentences = paragraph.split('. ')
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) + 2 <= max_length:
                            current_chunk += sentence + '. '
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sentence + '. '
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks

    async def search_wikipedia(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Wikipedia search."""
        query = update.message.text.strip()
        
        if not query:
            await update.message.reply_text("Please provide a search query!")
            return
        
        # Send "typing" action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Search for articles
            search_results = wikipedia.search(query, results=5)
            
            if not search_results:
                await update.message.reply_text(f"No results found for '{query}'. Try a different search term.")
                return
            
            # If multiple results, show options with better messaging
            if len(search_results) > 1:
                keyboard = []
                for i, result in enumerate(search_results[:5]):
                    # URL encode the result to handle special characters
                    import urllib.parse
                    encoded_result = urllib.parse.quote(result)
                    keyboard.append([InlineKeyboardButton(result, callback_data=f"wiki_{encoded_result}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                context.user_data['search_results'] = search_results
                
                await update.message.reply_text(
                    f"🎯 **Found {len(search_results)} results for '{query}'**\n\n"
                    f"📋 **Which one are you looking for?**",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                return
            
            # If only one result, get it directly
            await self.get_article(update.message, search_results[0])
            
        except wikipedia.exceptions.DisambiguationError as e:
            # Handle disambiguation
            keyboard = []
            options = e.options[:5]  # Show first 5 options
            
            for i, option in enumerate(options):
                # URL encode the option to handle special characters
                import urllib.parse
                encoded_option = urllib.parse.quote(option)
                keyboard.append([InlineKeyboardButton(option, callback_data=f"wiki_{encoded_option}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            context.user_data['search_results'] = options
            
            await update.message.reply_text(
                f"🎯 **'{query}' has multiple meanings**\n\n"
                f"📋 **Which specific topic do you want?**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await update.message.reply_text(f"An error occurred: {str(e)}")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks for article selection and options."""
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data.startswith('wiki_'):
                article_title = query.data[5:]  # Remove 'wiki_' prefix
                # URL decode the title to handle special characters
                import urllib.parse
                article_title = urllib.parse.unquote(article_title)
                await self.get_article(query.message, article_title)
            elif query.data.startswith('long_'):
                article_title = query.data[5:]  # Remove 'long_' prefix
                import urllib.parse
                article_title = urllib.parse.unquote(article_title)
                await self.get_longer_summary(query.message, article_title)
                
        except Exception as e:
            await query.message.reply_text(f"❌ **Oops! Something went wrong**\n\nPlease try searching again or choose a different topic.")

    async def get_longer_summary(self, message, title):
        """Send a longer, more detailed summary."""
        try:
            page = wikipedia.page(title)
            
            # Get longer summary (10 sentences)
            long_summary = wikipedia.summary(title, sentences=10)
            
            # Get key sections from content
            content = page.content
            sections = self.extract_main_sections(content)
            
            # Format the longer summary
            formatted_long_summary = self.format_summary_text(long_summary)
            
            # Build longer summary with proper markdown formatting
            detailed_summary = f"📚 **{page.title} - Detailed Summary**\n\n"
            detailed_summary += f"📖 **Comprehensive Overview:**\n{formatted_long_summary}\n\n"
            
            if sections:
                detailed_summary += f"📑 **Article Structure:**\n{sections}\n\n"
            
            detailed_summary += f"🔗 **Complete Article:**\n[Read on Wikipedia]({page.url})"
            
            # Split if too long
            chunks = self.split_text(detailed_summary, max_length=3500)
            
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply_text(chunk, parse_mode='Markdown')
                else:
                    await message.reply_text(f"*(Continued...)*\n\n{chunk}", parse_mode='Markdown')
                    
        except wikipedia.exceptions.PageError:
            await self.handle_page_not_found(message, title)
        except Exception as e:
            await message.reply_text(f"❌ **Sorry, couldn't load the detailed summary**\n\nTry the main summary or search for a different topic.")
    
    def extract_main_sections(self, content):
        """Extract main section headers and brief descriptions."""
        import re
        
        # Find section headers (== Section Name ==)
        sections = re.findall(r'==\s*([^=]+?)\s*==', content)
        
        if not sections:
            return None
            
        # Format first 5 sections as bullet points
        formatted_sections = []
        for section in sections[:5]:
            section = section.strip()
            if len(section) > 3 and section not in ['References', 'External links', 'See also']:
                formatted_sections.append(f"• {section}")
        
        return '\n'.join(formatted_sections) if formatted_sections else None
    
    async def handle_page_not_found(self, message, title):
        """Handle page not found errors with better UX and suggestions."""
        try:
            # Try to find similar articles
            search_results = wikipedia.search(title, results=5)
            
            if search_results:
                # Show alternative suggestions
                keyboard = []
                for result in search_results[:3]:  # Show top 3 suggestions
                    import urllib.parse
                    encoded_result = urllib.parse.quote(result)
                    keyboard.append([InlineKeyboardButton(result, callback_data=f"wiki_{encoded_result}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await message.reply_text(
                    f"🤔 **Couldn't find '{title}'**\n\n"
                    f"💡 **Did you mean one of these?**",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                # No suggestions available
                await message.reply_text(
                    f"🤔 **Couldn't find '{title}'**\n\n"
                    f"💡 **Try:**\n"
                    f"• Being more specific (e.g., 'Einstein physicist')\n"
                    f"• Using the full name\n"
                    f"• Checking your spelling\n"
                    f"• Searching for a related topic",
                    parse_mode='Markdown'
                )
        except Exception:
            # Fallback if even search fails
            await message.reply_text(
                f"🤔 **Couldn't find '{title}'**\n\n"
                f"💡 **Try searching for something else!**",
                parse_mode='Markdown'
            )

    async def get_article(self, message, title):
        """Fetch and send Wikipedia article summary."""
        try:
            # Get the article page
            page = wikipedia.page(title)
            
            # Create enhanced summary
            summary_text, image_url = await self.create_enhanced_summary(page)
            
            # Create inline keyboard for more options
            import urllib.parse
            keyboard = [
                [InlineKeyboardButton("📖 Read Full Article", url=page.url)],
                [InlineKeyboardButton("📝 Longer Summary", callback_data=f"long_{urllib.parse.quote(title)}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send featured image first if available
            if image_url:
                try:
                    await message.reply_photo(photo=image_url, caption=f"🖼️ Featured image for {page.title}")
                except Exception as e:
                    # Log the error for debugging
                    print(f"Image failed to load: {e}")
                    pass  # Continue without image if it fails
            
            # Send the enhanced summary
            await message.reply_text(summary_text, parse_mode='Markdown', reply_markup=reply_markup)
                
        except wikipedia.exceptions.PageError:
            # Handle page not found with better UX
            await self.handle_page_not_found(message, title)
        except Exception as e:
            await message.reply_text(f"❌ **Sorry, something went wrong**\n\nTry searching for a different topic or be more specific with your search.")
    
    async def create_enhanced_summary(self, page):
        """Create an enhanced, informative summary of the Wikipedia article."""
        try:
            # Get basic info
            title = page.title
            url = page.url
            
            # Get featured image if available
            image_url = self.get_featured_image(page)
            
            # Get a longer summary (5-7 sentences for better context)
            summary = wikipedia.summary(page.title, sentences=6)
            
            # Format the summary with better text styling
            formatted_summary = self.format_summary_text(summary)
            
            # Extract key sections from the article for additional context
            content = page.content
            key_info = self.extract_key_information(content)
            
            # Build the enhanced summary with proper markdown formatting
            enhanced_summary = f"📖 **{title}**\n\n"
            enhanced_summary += f"📋 **Overview:**\n{formatted_summary}\n\n"
            
            if key_info:
                enhanced_summary += f"💡 **Key Highlights:**\n{key_info}\n\n"
            
            enhanced_summary += f"🔗 **Read More:**\n[Full Wikipedia Article]({url})"
            
            return enhanced_summary, image_url
            
        except Exception as e:
            # Fallback to basic summary if enhanced fails
            basic_summary = wikipedia.summary(page.title, sentences=3)
            return f"📖 **{page.title}**\n\n{basic_summary}\n\n🔗 [Read more]({page.url})", None
    
    def extract_key_information(self, content):
        """Extract key bullet points from article content."""
        import re
        
        # Clean the content first
        content = self.clean_article_text(content)
        
        # Split into paragraphs
        paragraphs = content.split('\n\n')
        
        key_points = []
        
        # Look for the first few informative paragraphs (skip very short ones)
        for paragraph in paragraphs[:10]:  # Check first 10 paragraphs
            paragraph = paragraph.strip()
            
            # Skip short paragraphs, section headers, or reference-heavy content
            if (len(paragraph) > 100 and 
                len(paragraph) < 500 and 
                not paragraph.startswith('==') and
                paragraph.count('.') >= 2):  # Has multiple sentences
                
                # Extract the most informative sentence
                sentences = paragraph.split('. ')
                if sentences:
                    # Take the first substantial sentence
                    first_sentence = sentences[0].strip()
                    if len(first_sentence) > 50:
                        key_points.append(f"• {first_sentence}")
                        
                if len(key_points) >= 3:  # Limit to 3 key points
                    break
        
        return '\n'.join(key_points) if key_points else None
    
    def get_featured_image(self, page):
        """Extract the main infobox image from Wikipedia page."""
        try:
            # Get page images
            images = page.images
            
            if not images:
                return None
            
            # Look for the main article image (infobox image)
            # These are typically the first meaningful image
            excluded_patterns = [
                'commons-logo', 'wikimedia', 'edit-icon', 'wiki.png',
                'ambox', 'crystal', 'folder', 'nuvola', 'question_book',
                'magnify-clip', 'speaker', 'audio', 'ogg', 'sound'
            ]
            
            # Simply return the first valid image (usually the main one)
            for image_url in images[:3]:  # Check first 3 images only
                image_lower = image_url.lower()
                
                # Skip excluded patterns
                if any(pattern in image_lower for pattern in excluded_patterns):
                    continue
                
                # Return first valid image format
                if any(ext in image_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    return image_url
            
            return None  # Don't return random images
            
        except Exception:
            return None
    
    def format_summary_text(self, summary):
        """Add formatting to make summary text more readable."""
        import re
        
        # Split into sentences
        sentences = summary.split('. ')
        
        if not sentences:
            return summary
        
        formatted_sentences = []
        
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            
            if not sentence:
                continue
            
            # Add period back if not last sentence
            if i < len(sentences) - 1 and not sentence.endswith('.'):
                sentence += '.'
            
            # Bold important terms (years, numbers, proper nouns)
            # Bold years (4 digits)
            sentence = re.sub(r'\b(\d{4})\b', r'**\1**', sentence)
            
            # Bold percentages and large numbers
            sentence = re.sub(r'\b(\d+(?:,\d+)*(?:\.\d+)?%)\b', r'**\1**', sentence)
            sentence = re.sub(r'\b(\d+(?:,\d+)+)\b', r'**\1**', sentence)
            
            formatted_sentences.append(sentence)
        
        # Join with proper spacing and add emphasis to first sentence
        if formatted_sentences:
            formatted_sentences[0] = f"*{formatted_sentences[0]}*"
        
        return ' '.join(formatted_sentences)

    def clean_article_text(self, text):
        """Clean up Wikipedia article text."""
        import re
        
        # Remove multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove references like [1], [2], etc.
        text = re.sub(r'\[\d+\]', '', text)
        
        # Remove == Section == markers (keep the text)
        text = re.sub(r'==+ (.+?) ==+', r'\1', text)
        
        # Clean up extra spaces
        text = re.sub(r' +', ' ', text)
        
        return text.strip()

def main():
    """Start the bot."""
    # Create bot instance
    bot = WikipediaBot()
    
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.search_wikipedia))

    # Start the bot
    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
