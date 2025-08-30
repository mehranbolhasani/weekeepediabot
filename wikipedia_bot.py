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
            
            # If multiple results, show options
            if len(search_results) > 1:
                keyboard = []
                for i, result in enumerate(search_results[:5]):
                    keyboard.append([InlineKeyboardButton(result, callback_data=f"wiki_{result}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                context.user_data['search_results'] = search_results
                
                await update.message.reply_text(
                    f"Found multiple results for '{query}'. Please select one:",
                    reply_markup=reply_markup
                )
                return
            
            # If only one result, get it directly
            await self.get_article(update.message, search_results[0])
            
        except wikipedia.exceptions.DisambiguationError as e:
            # Handle disambiguation
            keyboard = []
            options = e.options[:5]  # Show first 5 options
            
            for i, option in enumerate(options):
                keyboard.append([InlineKeyboardButton(option, callback_data=f"wiki_{option}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            context.user_data['search_results'] = options
            
            await update.message.reply_text(
                f"'{query}' is ambiguous. Please select the specific topic:",
                reply_markup=reply_markup
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
                await self.get_article(query.message, article_title)
            elif query.data.startswith('long_'):
                article_title = query.data[5:]  # Remove 'long_' prefix
                await self.get_longer_summary(query.message, article_title)
                
        except Exception as e:
            await query.message.reply_text(f"Error loading article: {str(e)}")

    async def get_longer_summary(self, message, title):
        """Send a longer, more detailed summary."""
        try:
            page = wikipedia.page(title)
            
            # Get longer summary (10 sentences)
            long_summary = wikipedia.summary(title, sentences=10)
            
            # Get key sections from content
            content = page.content
            sections = self.extract_main_sections(content)
            
            # Build longer summary
            detailed_summary = f"📖 **{page.title}** - Detailed Summary\n\n"
            detailed_summary += f"📋 **Overview:**\n{long_summary}\n\n"
            
            if sections:
                detailed_summary += f"🔍 **Main Topics:**\n{sections}\n\n"
            
            detailed_summary += f"🔗 **Full Article:** [Wikipedia]({page.url})"
            
            # Split if too long
            chunks = self.split_text(detailed_summary, max_length=3500)
            
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply_text(chunk, parse_mode='Markdown')
                else:
                    await message.reply_text(f"*(Continued...)*\n\n{chunk}", parse_mode='Markdown')
                    
        except Exception as e:
            await message.reply_text(f"Error getting detailed summary: {str(e)}")
    
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

    async def get_article(self, message, title):
        """Fetch and send Wikipedia article summary."""
        try:
            # Get the article page
            page = wikipedia.page(title)
            
            # Create enhanced summary
            summary_text = await self.create_enhanced_summary(page)
            
            # Create inline keyboard for more options
            keyboard = [
                [InlineKeyboardButton("📖 Read Full Article", url=page.url)],
                [InlineKeyboardButton("📝 Longer Summary", callback_data=f"long_{title}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send the enhanced summary
            await message.reply_text(summary_text, parse_mode='Markdown', reply_markup=reply_markup)
                
        except wikipedia.exceptions.PageError:
            await message.reply_text(f"Page '{title}' not found. Try a different search term.")
        except Exception as e:
            await message.reply_text(f"Error retrieving article: {str(e)}")
    
    async def create_enhanced_summary(self, page):
        """Create an enhanced, informative summary of the Wikipedia article."""
        try:
            # Get basic info
            title = page.title
            url = page.url
            
            # Get a longer summary (5-7 sentences for better context)
            summary = wikipedia.summary(page.title, sentences=6)
            
            # Extract key sections from the article for additional context
            content = page.content
            key_info = self.extract_key_information(content)
            
            # Build the enhanced summary
            enhanced_summary = f"📖 **{title}**\n\n"
            enhanced_summary += f"📋 **Summary:**\n{summary}\n\n"
            
            if key_info:
                enhanced_summary += f"🔍 **Key Information:**\n{key_info}\n\n"
            
            enhanced_summary += f"🔗 **Read more:** [Wikipedia Article]({url})"
            
            return enhanced_summary
            
        except Exception as e:
            # Fallback to basic summary if enhanced fails
            return f"📖 **{page.title}**\n\n{wikipedia.summary(page.title, sentences=3)}\n\n🔗 [Read more]({page.url})"
    
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
