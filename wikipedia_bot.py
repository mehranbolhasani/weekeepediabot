import logging
import wikipedia
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Your bot token from BotFather
BOT_TOKEN = "8309264806:AAHZrguhnEwoRe4eC_enTkvcLlJ6-6REbYM"

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
                    keyboard.append([InlineKeyboardButton(result, callback_data=f"wiki_{i}_{result}")])
                
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
                keyboard.append([InlineKeyboardButton(option, callback_data=f"wiki_{i}_{option}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            context.user_data['search_results'] = options
            
            await update.message.reply_text(
                f"'{query}' is ambiguous. Please select the specific topic:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            await update.message.reply_text(f"An error occurred: {str(e)}")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks for article selection."""
        query = update.callback_query
        await query.answer()
        
        try:
            data_parts = query.data.split('_', 2)
            if len(data_parts) >= 3 and data_parts[0] == 'wiki':
                article_title = data_parts[2]
                await self.get_article(query.message, article_title)
                
        except Exception as e:
            await query.message.reply_text(f"Error loading article: {str(e)}")

    async def get_article(self, message, title):
        """Fetch and send Wikipedia article."""
        try:
            # Get the full article
            page = wikipedia.page(title)
            
            # Prepare article info
            article_info = f"📖 **{page.title}**\n\n"
            
            # Add summary first
            summary = wikipedia.summary(title, sentences=3)
            article_info += f"*Summary:*\n{summary}\n\n"
            
            # Add full content
            content = page.content
            
            # Remove references and clean up
            content = self.clean_article_text(content)
            
            full_text = article_info + content
            
            # Split into chunks if too long
            chunks = self.split_text(full_text)
            
            # Send article URL first
            await message.reply_text(f"🔗 **Wikipedia URL:** {page.url}")
            
            # Send content chunks
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply_text(chunk, parse_mode='Markdown')
                else:
                    await message.reply_text(f"*(Continued...)*\n\n{chunk}", parse_mode='Markdown')
                
                # Add small delay between messages to avoid rate limiting
                import asyncio
                await asyncio.sleep(0.5)
            
            # If article was split, show completion message
            if len(chunks) > 1:
                await message.reply_text(f"📋 Article complete! ({len(chunks)} parts)")
                
        except wikipedia.exceptions.PageError:
            await message.reply_text(f"Page '{title}' not found. Try a different search term.")
        except Exception as e:
            await message.reply_text(f"Error retrieving article: {str(e)}")

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
