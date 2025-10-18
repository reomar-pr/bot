"""
بوت آل بصيص المُطوّر - إصدار 2.0
بوت متكامل لإدارة الاستبيانات والأسئلة في مجموعات تليجرام
يجمع بين أفضل ميزات البوتات السابقة مع تحسينات جديدة
"""

import logging
import json
import os
import datetime
import shutil
import pandas as pd  # إضافة مكتبة pandas لتصدير البيانات إلى Excel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from config import TELEGRAM_BOT_TOKEN

# --- إعداد التسجيل والمتغيرات العامة ---

# إعداد التسجيل للمساعدة في تتبع الأخطاء
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_log.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# حالات المحادثة
# حالات إنشاء السؤال
ASK_QUESTION, ASK_OPTIONS, ASK_GROUP_IDS_CREATE = range(3)
# حالات إدارة الأسئلة
MANAGE_LIST_QUESTIONS, SELECT_MANAGE_ACTION, ASK_SHARE_GROUP_ID, CONFIRM_DELETE = range(3, 7)
# حالات عرض الإجابات
SELECT_QUESTION = 7
AWAITING_REPLY = 8

# حالات محادثة البث للمجموعات (تحديث)
BROADCAST_MESSAGE = 9
BROADCAST_GROUP_IDS = 10

# قاموس لحفظ الأسئلة وإجابات الطلاب
questions_db = {}  # سيخزن {question_id: {'question': text, 'options': [], 'answers': {user_id: {'answer': answer, 'name': name, 'username': username}}}}
question_counter = 1  # عداد للأسئلة يبدأ من 1

# معرفات المشرفين المسموح لهم باستخدام البوت (يمكن إضافة معرفات أو أرقام)
ALLOWED_USERS = [1687347144]  # معرفات رقمية
ALLOWED_USERNAMES = ["omr_taher", "Mohameddammar", "Mariam20235"]  # معرفات نصية

# --- متغيرات إضافية للرسائل ---
user_messages = {}  # {message_id: {'user_id': int, 'name': str, 'username': str, 'message': str, 'timestamp': str, 'replied': bool}}
message_counter = 1
user_message_counts = {}  # Track number of messages per user: {user_id: count}

# --- وظائف إدارة البيانات ---

def is_authorized(user):
    """التحقق من صلاحيات المستخدم بناءً على المعرف الرقمي أو اسم المستخدم."""
    # التحقق من المعرف الرقمي
    if user.id in ALLOWED_USERS:
        return True

    # التحقق من اسم المستخدم
    if user.username and user.username.lower() in [name.lower() for name in ALLOWED_USERNAMES]:
        return True

    return False

async def unauthorized_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة للمستخدمين غير المصرح لهم."""
    if update.message:
        await update.message.reply_text("عذرًا، لا تمتلك صلاحيات لاستخدام هذا الأمر.")
    elif update.callback_query:
        try:
            await update.callback_query.answer("عذرًا، لا تمتلك صلاحيات لهذا الإجراء.", show_alert=True)
        except TelegramError as e:
            logger.warning(f"Could not answer callback query for unauthorized access: {e}")

    return ConversationHandler.END

def format_date(dt):
    """تنسيق التاريخ بالشكل المطلوب"""
    if isinstance(dt, str):
        dt = datetime.datetime.fromisoformat(dt)
    return dt.strftime("%d/%m/%Y - %H:%M")

def save_data():
    """حفظ البيانات في ملف JSON."""
    global questions_db, question_counter, user_messages, message_counter, user_message_counts
    data = {
        'questions_db': questions_db,
        'question_counter': question_counter,
        'user_messages': user_messages,
        'message_counter': message_counter,
        'user_message_counts': user_message_counts,
        'last_saved': datetime.datetime.now().isoformat()  # Keep ISO format for storage
    }

    # إنشاء نسخة احتياطية قبل الحفظ
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, f'quiz_data_backup_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.json')

    if os.path.exists('quiz_data.json'):
        try:
            shutil.copy('quiz_data.json', backup_file)
            # حذف النسخ الاحتياطية القديمة إذا زادت عن 5
            backups = sorted(os.listdir(backup_dir))
            if len(backups) > 5:
                for old_backup in backups[:-5]:
                    os.remove(os.path.join(backup_dir, old_backup))
        except Exception as e:
            logger.error(f"خطأ في إنشاء نسخة احتياطية: {e}")

    # حفظ البيانات
    try:
        # Atomic write: write to a temp file then replace
        temp_file = 'quiz_data.json.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(temp_file, 'quiz_data.json')  # atomic on most OSes
        logger.info("تم حفظ البيانات بنجاح (atomic write)")
        return True
    except Exception as e:
        logger.error(f"Error saving data: {e}", exc_info=True)
        # For manual restore, rename quiz_data.json.tmp to quiz_data.json if it exists
        # and quiz_data.json is corrupted or missing.
        return False

def load_data():
    """تحميل البيانات من ملف JSON."""
    global questions_db, question_counter, user_messages, message_counter, user_message_counts

    # التحقق من وجود ملف البيانات
    if os.path.exists('quiz_data.json'):
        try:
            with open('quiz_data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                questions_db = data.get('questions_db', {})
                question_counter = data.get('question_counter', 1)
                user_messages = data.get('user_messages', {})
                message_counter = data.get('message_counter', 1)
                user_message_counts = data.get('user_message_counts', {})
            logger.info(f"تم تحميل البيانات بنجاح. عدد الأسئلة: {len(questions_db)}, عدد الرسائل: {len(user_messages)}")
            return True
        except Exception as e:
            logger.error(f"حدث خطأ أثناء تحميل البيانات: {e}")
            questions_db = {}
            question_counter = 1
            user_messages = {}
            message_counter = 1
            user_message_counts = {}
            return False
    else:
        logger.info("ملف البيانات غير موجود، سيتم إنشاء بيانات جديدة")
        questions_db = {}
        question_counter = 1
        user_messages = {}
        message_counter = 1
        user_message_counts = {}
        return True

def renumber_questions():
    """إعادة ترقيم الأسئلة بالتسلسل وحذف الفجوات."""
    global questions_db, question_counter

    if not questions_db:
        question_counter = 1
        return

    # إنشاء قاموس جديد بترقيم متسلسل
    new_questions_db = {}
    sorted_questions = sorted(questions_db.items(), key=lambda x: int(x[0]))

    # إعادة ترقيم الأسئلة
    for i, (_, question_data) in enumerate(sorted_questions, 1):
        new_questions_db[str(i)] = question_data

    # تحديث قاموس الأسئلة وعداد الأسئلة
    questions_db = new_questions_db
    question_counter = len(questions_db) + 1

    # حفظ التغييرات
    save_data()
    logger.info(f"تم إعادة ترقيم الأسئلة. عدد الأسئلة الآن: {len(questions_db)}")

def log_unprocessed_answer(question_id, user_id, answer, user_data):
    """تسجيل الإجابات غير المعالجة في ملف JSON."""
    log_file = "unprocessed_answers.json"
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                unprocessed_answers = json.load(f)
        else:
            unprocessed_answers = {}

        # إضافة الإجابة الجديدة
        unprocessed_answers.setdefault(question_id, []).append({
            'user_id': user_id,
            'answer': answer,
            'user_data': user_data,
            'timestamp': datetime.datetime.now().isoformat()
        })

        # حفظ الملف
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(unprocessed_answers, f, ensure_ascii=False, indent=4)
        logger.info(f"Logged unprocessed answer for Q{question_id} from user {user_id}")
    except Exception as e:
        logger.error(f"Error logging unprocessed answer: {e}")

def process_unprocessed_answers():
    """معالجة الإجابات غير المعالجة عند إعادة تشغيل البوت."""
    log_file = "unprocessed_answers.json"
    global questions_db

    if not os.path.exists(log_file):
        return

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            unprocessed_answers = json.load(f)

        for question_id, answers in unprocessed_answers.items():
            if question_id not in questions_db:
                logger.warning(f"Question {question_id} not found while processing unprocessed answers.")
                continue

            for entry in answers:
                user_id = entry['user_id']
                answer = entry['answer']
                user_data = entry['user_data']

                # تسجيل الإجابة في قاعدة البيانات
                questions_db[question_id]['answers'][str(user_id)] = {
                    'answer': answer,
                    'name': user_data.get('name', 'مستخدم'),
                    'username': user_data.get('username', 'غير متوفر'),
                    'timestamp': entry['timestamp']
                }
                logger.info(f"Processed unprocessed answer for Q{question_id} from user {user_id}")

        # حفظ التغييرات وحذف الملف
        save_data()
        os.remove(log_file)
        logger.info("Processed all unprocessed answers and cleared the log file.")
    except Exception as e:
        logger.error(f"Error processing unprocessed answers: {e}")

async def _generate_question_list_markup(callback_prefix: str):
    """إنشاء لوحة مفاتيح بقائمة الأسئلة مع بادئة callback محددة."""
    if not questions_db:
        return None, "لا توجد أسئلة مسجلة حتى الآن."

    keyboard = []
    # فرز الأسئلة حسب المعرف الرقمي
    sorted_q_ids = sorted(questions_db.keys(), key=int)

    for q_id in sorted_q_ids:
        q_data = questions_db[q_id]
        short_question = q_data['question'][:30] + "..." if len(q_data['question']) > 30 else q_data['question']
        keyboard.append([InlineKeyboardButton(f"سؤال {q_id}: {short_question}", callback_data=f"{callback_prefix}:{q_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup, "اختر السؤال المطلوب:"

# --- وظائف إنشاء سؤال جديد ---

async def ask_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ عملية إنشاء سؤال جديد."""
    if not update.message or not update.message.from_user:
        return ConversationHandler.END
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)

    if update.message:
        await update.message.reply_text("ما السؤال الذي تودّ طرحه على الطلاب؟")
    # تنظيف بيانات المستخدم القديمة
    if context.user_data is not None:
        context.user_data.clear()
    return ASK_QUESTION

async def ask_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل نص السؤال."""
    global question_counter

    if not update.message or not update.message.text:
        return ConversationHandler.END
    if context.user_data is None:
        return ConversationHandler.END
    context.user_data['new_question_text'] = update.message.text
    context.user_data['options'] = []

    await update.message.reply_text("الآن، أدخل جميع الإجابات المحتملة (كل إجابة في رسالة منفصلة). \nعند الانتهاء، استخدم /done.")
    return ASK_OPTIONS

async def receive_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل خيارات الإجابة."""
    if not update.message or not update.message.text:
        return ASK_OPTIONS
    option = update.message.text.strip() # إزالة المسافات الزائدة
    if context.user_data is None:
        return ASK_OPTIONS
    if option: # التأكد من أن الخيار ليس فارغاً
        context.user_data.setdefault('options', []).append(option) # طريقة آمنة للإضافة للقائمة
        await update.message.reply_text(f"أُضيفت الإجابة: {option}")
    else:
        await update.message.reply_text("لا يمكن إضافة خيار فارغ.")
    return ASK_OPTIONS # البقاء في نفس الحالة لاستقبال المزيد

async def done_adding_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ينهي إضافة الخيارات وينتقل لطلب الإجابة الصحيحة."""
    if context.user_data is None or not context.user_data.get('options'):
        if update.message:
            await update.message.reply_text("لم تقم بإدخال أي إجابات! الرجاء إدخال إجابة واحدة على الأقل أو استخدم /cancel.")
        return ASK_OPTIONS

    # Create inline keyboard with options for correct answer selection
    options = context.user_data.get('options', [])
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([InlineKeyboardButton(option, callback_data=f"correct:{i}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "اختر الإجابة الصحيحة من القائمة التالية:",
        reply_markup=reply_markup
    )
    return ASK_OPTIONS

async def set_correct_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديد الإجابة الصحيحة."""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("correct:"):
        return ASK_OPTIONS

    index = int(query.data.split(":")[1])
    options = context.user_data.get('options', [])
    if 0 <= index < len(options):
        context.user_data['correct_answer'] = options[index]
        await query.message.reply_text(
            f"تم تحديد الإجابة الصحيحة: {options[index]}\n\n"
            "الآن أرسل معرفات المجموعات التي تريد نشر السؤال بها:\n"
            "• يمكنك إرسال معرف واحد أو أكثر\n"
            "• ضع كل معرف في سطر جديد\n"
            "• يجب أن تبدأ المعرفات بـ '-'"
        )
        return ASK_GROUP_IDS_CREATE
    return ASK_OPTIONS

async def send_new_question_to_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ينشئ السؤال في قاعدة البيانات ويرسله للمجموعات المحددة."""
    global question_counter, questions_db

    if context.user_data is None:
        if update.message:
            await update.message.reply_text("حدث خطأ، معلومات السؤال غير مكتملة. الرجاء البدء من جديد بـ /ask.")
        return ConversationHandler.END
    group_ids = context.user_data.get('group_ids', [])
    question_text = context.user_data.get('new_question_text')
    options = context.user_data.get('options', [])

    if not group_ids:
        if update.message:
            await update.message.reply_text("لم تقم بإدخال أي معرفات مجموعات! الرجاء إدخال معرف واحد على الأقل أو استخدم /cancel.")
        return ASK_GROUP_IDS_CREATE

    if not question_text or not options:
         if update.message:
             await update.message.reply_text("حدث خطأ، معلومات السؤال غير مكتملة. الرجاء البدء من جديد بـ /ask.")
         if context.user_data is not None:
             context.user_data.clear() # تنظيف البيانات عند الخطأ
         return ConversationHandler.END

    # إنشاء معرف فريد للسؤال الآن فقط
    current_question_id = str(question_counter)
    question_counter += 1

    # تخزين السؤال في قاعدة البيانات
    questions_db[current_question_id] = {
        'question': question_text,
        'options': options,
        'answers': {}, # يبدأ فارغاً
        'group_ids': group_ids,
        'correct_answer': context.user_data.get('correct_answer')  # Add this line
    }

    # حفظ البيانات بعد إضافة السؤال
    save_data()

    logger.info(f"Question {current_question_id} created: {questions_db[current_question_id]}")

    # إنشاء أزرار بمعرفات فريدة تتضمن معرف السؤال والإجابة
    keyboard = []
    for i, option in enumerate(options):
        # تغيير صيغة callback_data لتكون أقصر
        callback_data = f"a:{current_question_id}:{i}"  # استخدام رقم الخيار بدلاً من النص
        keyboard.append([InlineKeyboardButton(option, callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    send_errors = []
    # إرسال السؤال والأزرار إلى كل مجموعة تم إدخال معرفها
    for group_id in group_ids:
        try:
            # إرسال السؤال بدون رقم السؤال للطلاب
            await context.bot.send_message(
                chat_id=group_id,
                text=f"{question_text}", # النص الأصلي للسؤال فقط
                reply_markup=reply_markup
            )
            logger.info(f"Question {current_question_id} sent to group {group_id}")
        except TelegramError as e:
            logger.error(f"Error sending Q{current_question_id} to group {group_id}: {e}", exc_info=True)
            send_errors.append(group_id)
        except Exception as e: # التقاط أي أخطاء أخرى
            logger.error(f"Unexpected error sending Q{current_question_id} to group {group_id}: {e}", exc_info=True)
            send_errors.append(group_id)

    # رسالة واحدة للمستخدم تلخص النتيجة
    if not send_errors:
         final_message = f"✅ تم تسجيل السؤال برقم: {current_question_id}\n" \
                         f"وتم إرساله بنجاح إلى {len(group_ids)} مجموعة/مجموعات."
    else:
         final_message = f"⚠️ تم تسجيل السؤال برقم: {current_question_id}\n" \
                         f"لكن حدثت مشكلة في الإرسال لـ {len(send_errors)} من أصل {len(group_ids)} مجموعة.\n" \
                         f"المجموعات التي فشل الإرسال إليها: {', '.join(send_errors)}"

    await update.message.reply_text(final_message)
    context.user_data.clear() # تنظيف بيانات المستخدم بعد الانتهاء
    return ConversationHandler.END

# --- وظائف استقبال إجابات الطلاب ---

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل إجابة الطالب عند النقر على زر."""
    query = update.callback_query
    if not query or not query.data or not query.from_user:
        return
    
    try:
        parts = query.data.split(":", 2)
        if len(parts) != 3 or parts[0] != "a":  # تغيير الشرط ليتناسب مع الصيغة الجديدة
            await query.answer("صيغة البيانات غير صحيحة.")
            return

        prefix, question_id, option_index = parts
        option_index = int(option_index)
        
        # Check if question exists
        if question_id not in questions_db:
            await query.answer("هذا السؤال لم يعد متاحًا.")
            return

        # Get the actual answer text from the options list
        options = questions_db[question_id]['options']
        if option_index >= len(options):
            await query.answer("خيار غير صالح.")
            return
            
        answer = options[option_index]

        # Check if user already answered
        if str(query.from_user.id) in questions_db[question_id]['answers']:
            old_answer = questions_db[question_id]['answers'][str(query.from_user.id)]['answer']
            await query.answer(f"سبق أن أجبت على هذا السؤال. إجابتك السابقة: {old_answer}", show_alert=True)
            return

        # Get correct answer
        correct_answer = questions_db[question_id]['correct_answer']
        
        # Check if answer is correct
        is_correct = answer == correct_answer
        
        # Save answer
        questions_db[question_id]['answers'][str(query.from_user.id)] = {
            'answer': answer,
            'name': f"{query.from_user.first_name} {query.from_user.last_name}".strip() if query.from_user.last_name else query.from_user.first_name,
            'username': query.from_user.username or "غير متوفر",
            'timestamp': datetime.datetime.now().isoformat(),
            'group_id': str(query.message.chat_id) if query.message else "غير متوفر"
        }
        
        save_data()

        # Show appropriate message
        if is_correct:
            await query.answer("إجابة صحيحة. ✅", show_alert=True)
        else:
            await query.answer(f"إجابتك خاطئة. ❌\n الإجابة الصحيحة هي: {correct_answer}", show_alert=True)

    except Exception as e:
        logger.error(f"Error handling answer: {e}")
        await query.answer("حدث خطأ في معالجة الإجابة.", show_alert=True)

# --- وظائف إدارة الأسئلة (/list) ---

async def list_questions_manage_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يبدأ محادثة إدارة الأسئلة بعرض القائمة."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)

    # تنظيف بيانات الجلسة
    context.user_data.clear()

    # إنشاء قائمة الأسئلة
    reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")

    if not reply_markup:
        await update.message.reply_text(message_text) # رسالة "لا توجد أسئلة"
        return ConversationHandler.END

    await update.message.reply_text("اختر السؤال الذي تريد إدارته:", reply_markup=reply_markup)
    return MANAGE_LIST_QUESTIONS

async def show_question_manage_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض خيارات الإدارة (مشاركة، حذف، عرض الإجابات، عودة) لسؤال محدد."""
    query = update.callback_query
    await query.answer()

    # استخلاص معرف السؤال من callback_data
    # الصيغة: "m_select:question_id"
    question_id = query.data.split(":", 1)[1]
    context.user_data['manage_question_id'] = question_id

    if question_id not in questions_db:
        await query.edit_message_text("عذرًا، لم يتم العثور على السؤال. قد يكون تم حذفه.")
        return ConversationHandler.END

    # استخراج بيانات السؤال
    question_data = questions_db[question_id]
    question_text = question_data['question']
    options = question_data['options']
    answer_count = len(question_data.get('answers', {}))

    # إنشاء نص الرسالة مع معلومات السؤال
    message = f"📝 <b>معلومات السؤال #{question_id}</b>\n\n"
    message += f"<b>السؤال:</b> {question_text}\n\n"

    # إضافة الخيارات
    message += "<b>الخيارات:</b>\n"
    for i, option in enumerate(options, 1):
        message += f"{i}. {option}\n"

    # إضافة عدد الإجابات
    message += f"\n<b>عدد الإجابات المستلمة:</b> {answer_count}"

    # إنشاء أزرار الإدارة
    keyboard = [
        [
            InlineKeyboardButton("عرض الإجابات 📊", callback_data=f"m_answers:{question_id}"),
        ],
        [
            InlineKeyboardButton("مشاركة السؤال 🔄", callback_data=f"m_share:{question_id}"),
            InlineKeyboardButton("حذف السؤال ❌", callback_data=f"m_delete:{question_id}"),
        ],
        [
            InlineKeyboardButton("« رجوع للقائمة", callback_data="m_back_list"),
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except TelegramError as e:
        logger.error(f"Error editing message: {e}")
        # محاولة إرسال رسالة جديدة إذا فشل تحرير الرسالة
        try:
            await query.delete_message()
        except:
            pass

        await query.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    return SELECT_MANAGE_ACTION

async def prompt_share_group_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يطلب معرف المجموعة لمشاركة السؤال فيها."""
    query = update.callback_query
    await query.answer()

    question_id = context.user_data.get('manage_question_id')
    if not question_id or question_id not in questions_db:
         try:
             await query.edit_message_text("حدث خطأ أو تم حذف السؤال. الرجاء البدء من /list.")
         except TelegramError as e: logger.warning(f"Could not edit message on missing Q in prompt_share: {e}")
         return ConversationHandler.END

    try:
        await query.edit_message_text(f"أرسل *معرف المجموعة* التي تريد إعادة نشر السؤال {question_id} فيها (يجب أن يبدأ بـ '-'):\nأو استخدم /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN)
    except TelegramError as e:
        logger.warning(f"Could not edit message in prompt_share_group_id: {e}")
        # إرسال رسالة جديدة إذا فشل التعديل
        await query.message.reply_text(f"أرسل *معرف المجموعة* التي تريد إعادة نشر السؤال {question_id} فيها (يجب أن يبدأ بـ '-'):\nأو استخدم /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN)

    return ASK_SHARE_GROUP_ID

async def share_question_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل معرف المجموعة ويعيد نشر السؤال المحدد."""
    group_id_input = update.message.text.strip()
    question_id = context.user_data.get('manage_question_id')
    admin_user_id = update.message.from_user.id

    if not question_id or question_id not in questions_db:
        await update.message.reply_text("لم يتم العثور على السؤال المحدد للإرسال. الرجاء البدء من /list.")
        return ConversationHandler.END

    if not (group_id_input.startswith('-') and group_id_input[1:].isdigit()):
         await update.message.reply_text(f"'{group_id_input}' ليس معرف مجموعة صالح. يجب أن يكون رقمًا ويبدأ بـ '-'.\n\nأرسل المعرف الصحيح أو استخدم /cancel.")
         return ASK_SHARE_GROUP_ID # يبقى في نفس الحالة لطلب المعرف مجدداً

    group_id = group_id_input
    question_data = questions_db[question_id]
    question_text = question_data['question']
    options = question_data['options']

    # إعادة إنشاء الأزرار بنفس الـ callback data لضمان تسجيل الإجابات بشكل صحيح
    keyboard = []
    for i, option in enumerate(options):
        callback_data = f"a:{question_id}:{i}"  # تغيير الصيغة لتتطابق مع الصيغة الجديدة
        keyboard.append([InlineKeyboardButton(option, callback_data=callback_data)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=f"{question_text}", # نفس نص السؤال
            reply_markup=reply_markup
        )
        await update.message.reply_text(f"✅ تم إعادة إرسال السؤال {question_id} إلى المجموعة: {group_id}")
        logger.info(f"Admin {admin_user_id} reshared question {question_id} to group {group_id}")
        return ConversationHandler.END
    except TelegramError as e:
        logger.error(f"Error sharing question {question_id} to group {group_id}: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ حدث خطأ أثناء إرسال السؤال إلى المجموعة {group_id}. تأكد أن البوت عضو ومشرف في المجموعة.\n\nيمكنك محاولة إرسال المعرف مرة أخرى أو استخدام /cancel.")
        return ASK_SHARE_GROUP_ID # البقاء في نفس الحالة لإعادة المحاولة
    except Exception as e:
         logger.error(f"Unexpected error sharing question {question_id} to group {group_id}: {e}", exc_info=True)
         await update.message.reply_text(f"⚠️ حدث خطأ غير متوقع أثناء الإرسال للمجموعة {group_id}. حاول مرة أخرى أو استخدم /cancel.")
         return ASK_SHARE_GROUP_ID

async def prompt_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض رسالة تأكيد قبل حذف السؤال."""
    query = update.callback_query
    await query.answer()

    question_id = context.user_data.get('manage_question_id')
    if not question_id or question_id not in questions_db:
         try:
            await query.edit_message_text("حدث خطأ أو تم حذف السؤال بالفعل. الرجاء البدء من /list.")
         except TelegramError as e: logger.warning(f"Could not edit msg on missing Q in prompt_delete: {e}")
         return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("‼️ نعم، احذف السؤال", callback_data=f"m_delete_confirm:{question_id}")],
        [InlineKeyboardButton("❌ إلغاء الحذف", callback_data=f"m_delete_cancel:{question_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(
            f"🚨 *تحذير:* هل أنت متأكد أنك تريد حذف السؤال *{question_id}* وكل إجاباته؟\n\n"
            f"_{questions_db[question_id]['question']}_\n\n"
            f"*لا يمكن التراجع عن هذا الإجراء!*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
         logger.warning(f"Could not edit message in prompt_delete_confirmation: {e}")
         # ارسال رسالة جديدة كبديل
         await query.message.reply_text(
            f"🚨 *تحذير:* هل أنت متأكد أنك تريد حذف السؤال *{question_id}* وكل إجاباته؟\n\n"
            f"_{questions_db[question_id]['question']}_\n\n"
            f"*لا يمكن التراجع عن هذا الإجراء!*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    return CONFIRM_DELETE

async def delete_question_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يحذف السؤال بعد التأكيد."""
    query = update.callback_query
    admin_user_id = query.from_user.id

    await query.answer("جاري الحذف...")

    try:
        prefix, question_id_from_callback = query.data.split(':', 1)
        if prefix != "m_delete_confirm":
             logger.warning(f"Ignored delete confirm callback with wrong prefix: {query.data}")
             return CONFIRM_DELETE
    except ValueError:
        logger.error(f"Invalid delete confirm callback data format: {query.data}")
        try:
            await query.edit_message_text("حدث خطأ في البيانات.")
        except TelegramError as e: logger.warning(f"Could not edit message on bad delete confirm data: {e}")
        return ConversationHandler.END

    # الحصول على معرف السؤال من محادثة المستخدم
    question_id = context.user_data.get('manage_question_id')

    # التحقق من تطابق المعرفين
    if question_id != question_id_from_callback:
        logger.error(f"Question ID mismatch in delete: user_data={question_id}, callback={question_id_from_callback}")
        try:
            await query.edit_message_text("حدث خطأ في تطابق بيانات السؤال.")
        except TelegramError as e: logger.warning(f"Could not edit message on Q ID mismatch: {e}")
        return ConversationHandler.END

    # التحقق من وجود السؤال
    if question_id not in questions_db:
        try:
            await query.edit_message_text("هذا السؤال غير موجود أو تم حذفه بالفعل.")
        except TelegramError as e: logger.warning(f"Could not edit message for already deleted Q: {e}")
        return ConversationHandler.END

    # حذف السؤال
    deleted_question = questions_db.pop(question_id, None)
    # إعادة ترقيم الأسئلة تلقائيًا بعد الحذف
    renumber_questions()
    # حفظ التغييرات فوراً
    save_data()

    logger.info(f"Admin {admin_user_id} deleted question {question_id}")

    # تنظيف بيانات المستخدم
    context.user_data.pop('manage_question_id', None)

    try:
        await query.edit_message_text(
            f"✅ تم حذف السؤال {question_id} بنجاح.\n\n"
            f"السؤال المحذوف: {deleted_question['question']}\n"
            f"عدد الإجابات المحذوفة: {len(deleted_question['answers'])}"
        )
    except TelegramError as e:
        logger.warning(f"Could not edit message after delete: {e}")
        # محاولة إرسال رسالة جديدة
        await query.message.reply_text(
            f"✅ تم حذف السؤال {question_id} بنجاح.\n\n"
            f"السؤال المحذوف: {deleted_question['question']}\n"
            f"عدد الإجابات المحذوفة: {len(deleted_question['answers'])}"
        )

    return ConversationHandler.END

async def cancel_delete_back_to_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يلغي عملية الحذف ويعود لقائمة خيارات إدارة السؤال."""
    query = update.callback_query
    await query.answer("تم إلغاء الحذف")

    try:
        prefix, question_id = query.data.split(':', 1)
        if prefix != "m_delete_cancel":
            logger.warning(f"Ignored delete cancel callback with wrong prefix: {query.data}")
            return CONFIRM_DELETE
    except ValueError:
        logger.error(f"Invalid delete cancel callback data format: {query.data}")
        return ConversationHandler.END

    if question_id not in questions_db:
        await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه). الرجاء البدء من /list.")
        return ConversationHandler.END

    # العودة لعرض خيارات إدارة السؤال
    question_text = questions_db[question_id]['question']

    keyboard = [
        [
            InlineKeyboardButton("عرض الإجابات 📊", callback_data=f"m_answers:{question_id}"),
        ],
        [
            InlineKeyboardButton("مشاركة السؤال 🔄", callback_data=f"m_share:{question_id}"),
            InlineKeyboardButton("حذف السؤال ❌", callback_data=f"m_delete:{question_id}"),
        ],
        [
            InlineKeyboardButton("« رجوع للقائمة", callback_data="m_back_list"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
            f"اختر الإجراء المطلوب:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        logger.warning(f"Could not edit message in cancel_delete: {e}")
        await query.message.reply_text(
            f"*إدارة السؤال {question_id}:*\n_{question_text}_\n\n"
            f"اختر الإجراء المطلوب:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    return SELECT_MANAGE_ACTION

async def back_to_manage_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعود إلى قائمة الأسئلة الرئيسية للإدارة."""
    query = update.callback_query
    await query.answer()

    # تنظيف معرف السؤال الحالي
    context.user_data.pop('manage_question_id', None)

    # إنشاء قائمة محدثة بالأسئلة
    reply_markup, message_text = await _generate_question_list_markup(callback_prefix="m_select")

    if not reply_markup:
        await query.edit_message_text(message_text) # رسالة "لا توجد أسئلة"
        return ConversationHandler.END

    await query.edit_message_text("اختر السؤال الذي تريد إدارته:", reply_markup=reply_markup)
    return MANAGE_LIST_QUESTIONS

async def show_question_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of groups for a question, then shows answers for the selected group."""
    query = update.callback_query
    await query.answer()

    # Extract question ID from callback data
    try:
        prefix, question_id = query.data.split(':', 1)
        if prefix != "m_answers":
            logger.warning(f"Ignored answers callback with wrong prefix: {query.data}")
            await query.edit_message_text("حدث خطأ في معالجة البيانات.")
            return ConversationHandler.END
    except ValueError:
        logger.error(f"Invalid show_answers callback data format: {query.data}")
        await query.edit_message_text("حدث خطأ في صيغة البيانات.")
        return ConversationHandler.END

    # Check if the question exists
    if question_id not in questions_db:
        await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه).")
        return ConversationHandler.END

    question_data = questions_db[question_id]
    group_ids = question_data.get('group_ids', [])

    if not group_ids:
        await query.edit_message_text("لم يتم إرسال هذا السؤال إلى أي مجموعة.")
        return ConversationHandler.END

    # Fetch group names for the group IDs
    keyboard = []
    for group_id in group_ids:
        try:
            chat = await context.bot.get_chat(group_id)
            group_name = chat.title
        except TelegramError as e:
            logger.warning(f"Failed to fetch group name for {group_id}: {e}")
            group_name = f"مجموعة غير معروفة ({group_id})"

        keyboard.append([InlineKeyboardButton(group_name, callback_data=f"m_answers_group:{question_id}:{group_id}")])

    keyboard.append([InlineKeyboardButton("« رجوع", callback_data="m_back_list")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"اختر المجموعة لعرض إجابات السؤال {question_id}:",
        reply_markup=reply_markup
    )
    return SELECT_MANAGE_ACTION

async def show_group_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays answers for a specific group."""
    query = update.callback_query
    await query.answer()

    # Extract question ID and group ID from callback data
    try:
        prefix, question_id, group_id = query.data.split(':', 2)
        if prefix != "m_answers_group":
            logger.warning(f"Ignored group answers callback with wrong prefix: {query.data}")
            await query.edit_message_text("حدث خطأ في معالجة البيانات.")
            return ConversationHandler.END
    except ValueError:
        logger.error(f"Invalid group answers callback data format: {query.data}")
        await query.edit_message_text("حدث خطأ في صيغة البيانات.")
        return ConversationHandler.END

    # Check if the question exists
    if question_id not in questions_db:
        await query.edit_message_text("هذا السؤال غير موجود (ربما تم حذفه).")
        return ConversationHandler.END

    question_data = questions_db[question_id]
    answers_dict = question_data.get('answers', {})

    # Filter answers for the selected group
    group_answers = {
        user_id: data for user_id, data in answers_dict.items() if data.get('group_id') == group_id
    }

    if not group_answers:
        await query.edit_message_text(f"لا توجد إجابات لهذا السؤال في المجموعة {group_id}.")
        return ConversationHandler.END

    # Prepare answers details
    answers_details = []
    for user_id, user_data in group_answers.items():
        full_name = user_data.get('name', 'مستخدم')
        if user_data.get('username'):
            full_name += f" (@{user_data['username']})"
        answer = user_data.get('answer', 'غير معروفة')
        timestamp = user_data.get('timestamp', '')

        # Format timestamp if available
        time_str = f" ({format_date(timestamp)})" if timestamp else ""

        answers_details.append(f"{full_name}{time_str}: {answer}")

    answers_text = "\n".join(answers_details)

    # Add a "Back" button to the keyboard
    keyboard = [[InlineKeyboardButton("« رجوع", callback_data=f"m_answers:{question_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Display answers
    try:
        await query.edit_message_text(
            f"📊 *إجابات السؤال {question_id} في المجموعة {group_id}:*\n\n{answers_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except TelegramError as e:
        logger.error(f"Error displaying group answers for Q{question_id} in group {group_id}: {e}")
        await query.edit_message_text(
            f"إجابات السؤال {question_id} في المجموعة {group_id}:\n\n{answers_text}",
            reply_markup=reply_markup
        )

    return SELECT_MANAGE_ACTION

# --- وظائف إضافية مفيدة ---

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تصدير بيانات الأسئلة والإجابات كملف Excel مع إضافة خانة اسم المجموعة."""
    user = update.message.from_user
    if not is_authorized(user):
        return await unauthorized_access(update, context)

    if not questions_db:
        await update.message.reply_text("لا توجد بيانات للتصدير حاليًا.")
        return

    # Runtime check for xlsxwriter
    try:
        import xlsxwriter
    except ImportError:
        await update.message.reply_text("⚠️ مكتبة xlsxwriter غير مثبتة على الخادم. الرجاء تثبيتها باستخدام الأمر:\n\npip install xlsxwriter\n\nثم أعد تشغيل البوت.")
        return

    # إنشاء نسخة من البيانات للتصدير
    export_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    export_filename = f"quiz_export_{export_time}.xlsx"

    try:
        # تحويل البيانات إلى DataFrame
        questions_list = []
        for q_id, q_data in questions_db.items():
            for user_id, answer_data in q_data['answers'].items():
                group_id = answer_data.get('group_id', 'غير متوفر')
                try:
                    # محاولة الحصول على اسم المجموعة
                    chat = await context.bot.get_chat(group_id)
                    group_name = chat.title
                except TelegramError:
                    group_name = f"مجموعة غير معروفة ({group_id})"

                questions_list.append({
                    "معرف السؤال": q_id,
                    "السؤال": q_data['question'],
                    "الخيار": answer_data['answer'],
                    "اسم المستخدم": answer_data.get('name', 'غير متوفر'),
                    "اسم المستخدم (Username)": answer_data.get('username', 'غير متوفر'),
                    "تاريخ الإجابة": answer_data.get('timestamp', 'غير متوفر'),
                    "معرف المجموعة": group_id,
                    "اسم المجموعة": group_name
                })

        df = pd.DataFrame(questions_list)

        # حفظ البيانات في ملف Excel
        with pd.ExcelWriter(export_filename, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='الأسئلة والإجابات')

        # إرسال الملف للمستخدم
        with open(export_filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=export_filename,
                caption=f"تصدير بيانات بوت آل بصيص\nعدد الأسئلة: {len(questions_db)}\nتاريخ التصدير: {export_time}"
            )

        # حذف الملف المؤقت
        try:
            os.remove(export_filename)
        except:
            pass

        logger.info(f"User {user.id} exported quiz data with {len(questions_db)} questions to Excel")

    except Exception as e:
        logger.error(f"Error exporting data to Excel: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ حدث خطأ أثناء تصدير البيانات: {e}")

# --- وظائف الرسائل ---

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رسائل المستخدمين غير المصرح لهم"""
    global message_counter, user_messages, user_message_counts

    if not update.message or not update.message.chat or update.message.chat.type != "private":
        return

    user = update.message.from_user if update.message else None

    if user and not is_authorized(user):
        message = ""
        photo_file_id = None
        
        if update.message.photo:
            # Get the highest resolution photo
            photo_file_id = update.message.photo[-1].file_id
            message = update.message.caption or "صورة بدون نص"
        elif update.message.text:
            message = update.message.text.strip()
        else:
            await update.message.reply_text("عذراً، يمكنك إرسال نص أو صورة فقط.")
            return

        message_id = str(message_counter)
        user_messages[message_id] = {
            'user_id': user.id,
            'name': f"{user.first_name} {getattr(user, 'last_name', '')}".strip(),
            'username': user.username or "غير متوفر",
            'message': message,
            'photo_file_id': photo_file_id,
            'timestamp': datetime.datetime.now().isoformat(),
            'replied': False
        }

        user_message_counts[user.id] = user_message_counts.get(user.id, 0) + 1
        message_counter += 1
        save_data()

        await update.message.reply_text("تم استلام رسالتك بنجاح ✅")
        if context.user_data is not None:
            context.user_data['awaiting_message'] = True

async def list_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المستخدمين ورسائلهم"""
    if not is_authorized(update.message.from_user):
        return await unauthorized_access(update, context)

    if not user_messages:
        await update.message.reply_text("لا توجد رسائل جديدة.")
        return

    # Group messages by user
    users = {}
    for msg_id, data in user_messages.items():
        user_id = data['user_id']
        if user_id not in users:
            users[user_id] = {
                'name': data['name'],
                'username': data['username'],
                'count': user_message_counts.get(user_id, 1)
            }

    # Create inline keyboard with user list
    keyboard = []
    for user_id, user_data in users.items():
        btn_text = f"{user_data['name']} (@{user_data['username']}) - {user_data['count']} رسائل"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"show_msgs:{user_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر المستخدم لعرض رسائله:", reply_markup=reply_markup)

async def show_user_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض رسائل مستخدم محدد"""
    query = update.callback_query
    await query.answer()

    user_id = query.data.split(':')[1]
    keyboard = []

    for msg_id, data in user_messages.items():
        if str(data['user_id']) == user_id:
            status = "✅" if data['replied'] else "❌"
            timestamp = format_date(data['timestamp'])

            # First send message details
            message_text = f"رسالة #{msg_id} {status}\n"
            message_text += f"التاريخ: {timestamp}\n"

            if data.get('photo_file_id'):
                try:
                    # Send photo with caption
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=data['photo_file_id'],
                        caption=message_text + f"النص المرفق: {data['message']}"
                    )
                except TelegramError as e:
                    logger.error(f"Error sending photo: {e}")
                    await query.message.reply_text(
                        message_text + f"(تعذر عرض الصورة)\nالنص المرفق: {data['message']}"
                    )
            else:
                # Text only message
                message_text += f"الرسالة: {data['message']}"
                await query.message.reply_text(message_text)

            # Add action buttons
            if not data['replied']:
                keyboard.append([
                    InlineKeyboardButton(f"الرد على رسالة #{msg_id}", callback_data=f"reply:{msg_id}"),
                    InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_msg:{msg_id}")
                ])
            else:
                keyboard.append([InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_msg:{msg_id}")])

    keyboard.append([InlineKeyboardButton("« رجوع", callback_data="back_to_users")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.message.reply_text(
            "قائمة التحكم بالرسائل:",
            reply_markup=reply_markup
        )
    except TelegramError as e:
        logger.error(f"Error showing user messages: {e}")
        await query.message.reply_text("حدث خطأ في عرض الرسائل")

async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف رسالة مستخدم"""
    query = update.callback_query
    await query.answer()

    msg_id = query.data.split(':')[1]
    if msg_id in user_messages:
        user_id = user_messages[msg_id]['user_id']
        user_message_counts[user_id] = max(0, user_message_counts.get(user_id, 1) - 1)
        del user_messages[msg_id]
        save_data()  # Save after deleting message
        # Return to user messages view
        await show_user_messages(update, context)

async def back_to_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """العودة لقائمة المستخدمين"""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user):
        return await unauthorized_access(update, context)

    # Group messages by user
    users = {}
    for msg_id, data in user_messages.items():
        user_id = data['user_id']
        if user_id not in users:
            users[user_id] = {
                'name': data['name'],
                'username': data['username'],
                'count': user_message_counts.get(user_id, 1)
            }

    # Create inline keyboard with user list
    keyboard = []
    for user_id, user_data in users.items():
        btn_text = f"{user_data['name']} (@{user_data['username']}) - {user_data['count']} رسائل"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"show_msgs:{user_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await query.edit_message_text(
            "اختر المستخدم لعرض رسائله:",
            reply_markup=reply_markup
        )
    except TelegramError as e:
        logger.error(f"Error returning to users list: {e}")
        await query.message.reply_text("حدث خطأ في العودة للقائمة")

# --- وظائف الرد على الرسائل ---

async def start_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء الرد على رسالة معينة."""
    query = update.callback_query
    await query.answer()

    msg_id = query.data.split(':')[1]
    if msg_id not in user_messages:
        await query.edit_message_text("الرسالة غير موجودة أو تم حذفها.")
        return ConversationHandler.END

    context.user_data['reply_to_msg_id'] = msg_id
    await query.edit_message_text("اكتب الرد على الرسالة أو استخدم /cancel لإلغاء العملية.")
    return AWAITING_REPLY

async def send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال الرد على الرسالة."""
    msg_id = context.user_data.get('reply_to_msg_id')
    if not msg_id or msg_id not in user_messages:
        await update.message.reply_text("الرسالة غير موجودة أو تم حذفها.")
        return ConversationHandler.END

    reply_text = update.message.text.strip()
    user_id = user_messages[msg_id]['user_id']

    try:
        # Format the reply message with the prefix
        formatted_reply = f"الرد من الإدارة:\n\n{reply_text}"
        await context.bot.send_message(
            chat_id=user_id,
            text=formatted_reply
        )
        user_messages[msg_id]['replied'] = True
        save_data()  # Save after marking message as replied
        await update.message.reply_text("تم إرسال الرد بنجاح.")

        # Show the users list again
        await list_messages(update, context)
        return ConversationHandler.END
    except TelegramError as e:
        logger.error(f"Error sending reply to user {user_id}: {e}")
        await update.message.reply_text("حدث خطأ أثناء إرسال الرد.")
        return ConversationHandler.END

# --- وظائف عامة ---

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء المحادثة الحالية."""
    if update.message:
        await update.message.reply_text("تم إلغاء العملية الحالية.")
    elif update.callback_query:
        await update.callback_query.answer("تم إلغاء العملية")
        try:
            await update.callback_query.edit_message_text("تم إلغاء العملية الحالية.")
        except TelegramError:
            pass

    # تنظيف بيانات المستخدم في الحالة
    if context.user_data:
        context.user_data.clear()

    logger.info(f"User {update.effective_user.id} cancelled conversation")
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض رسالة الترحيب أو يتيح إرسال رسالة للدعم."""
    user = update.message.from_user

    if not is_authorized(user):
        await update.message.reply_text("تفضل بإرسال رسالتك إلى مجتمع بصيص 📩\n\nأرفق اسمك أول الرسالة، واسم مجموعتك إن كنت سترسل التكليف.")
        context.user_data['awaiting_message'] = True
        return

    await update.message.reply_text(
        f"أهلاً {user.first_name}! مرحبًا بك في بوت آل بصيص المُطور 🌟\n\n"
        "الأوامر المتوفرة:\n"
        "◾️ /ask - إنشاء سؤال جديد\n"
        "◾️ /list - عرض الأسئلة وإدارتها\n"
        "◾️ /cancel - لإلغاء العملية الحالية\n"
        "◾️ /export - تصدير البيانات\n"
        "◾️ /messages - عرض رسائل المستخدمين\n"
        "◾️ /broadcast - إرسال رسالة مخصصة إلى المجموعات\n"
    )

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية البث: طلب الرسالة من المستخدم."""
    if not is_authorized(update.message.from_user):
        return await unauthorized_access(update, context)

    await update.message.reply_text(
        "أرسل رسالتك للبث:"
    )
    context.user_data.clear()  # تنظيف أي بيانات سابقة
    return BROADCAST_MESSAGE

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسالة المراد بثها وطلب معرفات المجموعات."""
    if not update.message:
        return BROADCAST_MESSAGE

    # حفظ محتوى الرسالة
    context.user_data['broadcast_data'] = {
        'photo': None,
        'text': None,
        'photo_file_id': None,
        'document': None,
        'document_file_id': None
    }

    if update.message.photo:
        # حفظ أكبر نسخة من الصورة
        context.user_data['broadcast_data']['photo_file_id'] = update.message.photo[-1].file_id
        context.user_data['broadcast_data']['text'] = update.message.caption

    elif update.message.document:
        # حفظ الملف
        context.user_data['broadcast_data']['document_file_id'] = update.message.document.file_id
        context.user_data['broadcast_data']['text'] = update.message.caption

    elif update.message.text:
        context.user_data['broadcast_data']['text'] = update.message.text
    else:
        await update.message.reply_text("الرجاء إرسال نص أو صورة أو ملف فقط.")
        return BROADCAST_MESSAGE

    await update.message.reply_text(
        "تم استلام الرسالة. الآن أرسل معرفات المجموعات التي تريد البث إليها.\n"
        "• يمكنك إرسال معرف واحد أو أكثر\n"
        "• ضع كل معرف في سطر جديد\n"
        "• يجب أن تبدأ المعرفات بـ '-'"
    )
    return BROADCAST_GROUP_IDS

async def broadcast_group_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال الرسالة إلى المجموعات المحددة."""
    if not update.message or not update.message.text:
        await update.message.reply_text("الرجاء إرسال معرفات المجموعات.")
        return BROADCAST_GROUP_IDS

    # معالجة معرفات المجموعات
    group_ids = update.message.text.strip().replace(',', '\n').splitlines()
    group_ids = [gid.strip() for gid in group_ids if gid.strip() and gid.strip().startswith('-')]

    if not group_ids:
        await update.message.reply_text(
            "لم يتم العثور على معرفات مجموعات صالحة.\n"
            "تأكد أن كل معرف يبدأ بـ '-'"
        )
        return BROADCAST_GROUP_IDS

    broadcast_data = context.user_data.get('broadcast_data', {})
    text = broadcast_data.get('text')
    photo_id = broadcast_data.get('photo_file_id')
    document_id = broadcast_data.get('document_file_id')

    success = []
    errors = []

    # إرسال الرسالة لكل مجموعة
    for group_id in group_ids:
        try:
            if photo_id:
                await context.bot.send_photo(
                    chat_id=group_id,
                    photo=photo_id,
                    caption=text
                )
            elif document_id:
                await context.bot.send_document(
                    chat_id=group_id,
                    document=document_id,
                    caption=text
                )
            else:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=text
                )
            success.append(group_id)
        except TelegramError as e:
            errors.append(group_id)
            logger.error(f"Error broadcasting to group {group_id}: {e}")

    # إرسال تقرير النتائج
    result_msg = "✅ نتائج عملية البث:\n\n"
    if success:
        result_msg += f"تم الإرسال بنجاح إلى {len(success)} مجموعة\n"
    if errors:
        result_msg += f"\n⚠️ فشل الإرسال إلى {len(errors)} مجموعة:\n{', '.join(errors)}"

    await update.message.reply_text(result_msg)
    context.user_data.clear()  # تنظيف البيانات بعد الانتهاء
    return ConversationHandler.END

async def receive_group_ids_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يستقبل معرفات المجموعات لإنشاء السؤال."""
    if not update.message or not update.message.text:
        return ASK_GROUP_IDS_CREATE

    # معالجة معرفات المجموعات
    group_ids = update.message.text.strip().replace(',', '\n').splitlines()
    group_ids = [gid.strip() for gid in group_ids if gid.strip() and gid.strip().startswith('-')]

    if not group_ids:
        await update.message.reply_text(
            "لم يتم العثور على معرفات مجموعات صالحة.\n"
            "تأكد أن كل معرف يبدأ بـ '-'"
        )
        return ASK_GROUP_IDS_CREATE

    context.user_data['group_ids'] = group_ids
    group_list = "\n".join(group_ids)
    await update.message.reply_text(
        f"تم استلام معرفات المجموعات التالية:\n\n{group_list}\n\n"
        "استخدم /send لإرسال السؤال إلى هذه المجموعات أو أرسل معرفات جديدة لتغيير القائمة."
    )
    return ASK_GROUP_IDS_CREATE

def main():
    """النقطة الرئيسية للبوت."""
    # تحميل البيانات المحفوظة
    load_data()

    # معالجة الإجابات غير المعالجة
    process_unprocessed_answers()

    # استخدام رمز API من config.py
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # --- ConversationHandler لإرسال رسالة مخصصة إلى المجموعات (/broadcast) ---
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler('broadcast', broadcast_start)],
        states={
            BROADCAST_MESSAGE: [
                MessageHandler(
                    filters.TEXT | filters.PHOTO | filters.Document.ALL,
                    broadcast_message
                )
            ],
            BROADCAST_GROUP_IDS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    broadcast_group_ids
                )
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name="broadcast_conversation",
        persistent=False
    )
    app.add_handler(broadcast_handler)

    # --- ConversationHandler لإنشاء سؤال جديد (/ask) ---
    create_question_handler = ConversationHandler(
        entry_points=[CommandHandler('ask', ask_question_start)],
        states={
            ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_question_received)],
            ASK_OPTIONS: [
                CommandHandler('done', done_adding_options),
                CallbackQueryHandler(set_correct_answer, pattern=r"^correct:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_options),
            ],
            ASK_GROUP_IDS_CREATE: [
                CommandHandler('send', send_new_question_to_groups),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group_ids_create),
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name="create_question_conversation",
        persistent=False
    )

    # --- ConversationHandler لإدارة الأسئلة (/list) ---
    manage_questions_handler = ConversationHandler(
        entry_points=[CommandHandler('list', list_questions_manage_start)],
        states={
            MANAGE_LIST_QUESTIONS: [CallbackQueryHandler(show_question_manage_options, pattern=r"^m_select:")],
            SELECT_MANAGE_ACTION: [
                CallbackQueryHandler(prompt_share_group_id, pattern=r"^m_share:"),
                CallbackQueryHandler(prompt_delete_confirmation, pattern=r"^m_delete:"),
                CallbackQueryHandler(show_question_answers, pattern=r"^m_answers:"),
                CallbackQueryHandler(show_group_answers, pattern=r"^m_answers_group:"),
                CallbackQueryHandler(back_to_manage_list, pattern=r"^m_back_list$")
            ],
            ASK_SHARE_GROUP_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, share_question_to_group)],
            CONFIRM_DELETE: [
                CallbackQueryHandler(delete_question_confirmed, pattern=r"^m_delete_confirm:"),
                CallbackQueryHandler(cancel_delete_back_to_options, pattern=r"^m_delete_cancel:")
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name="manage_questions_conversation",
        persistent=False,
        per_message=False
    )

    # --- ConversationHandler للرد على الرسائل ---
    reply_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reply, pattern=r"^reply:")],
        states={
            AWAITING_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_reply)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name="reply_conversation",
        persistent=False,
    )

    # --- ربط الأوامر العامة ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("export", export_data))

    # --- ربط محادثات البوت ---
    app.add_handler(create_question_handler)  # محادثة إنشاء سؤال
    app.add_handler(manage_questions_handler) # محادثة إدارة الأسئلة
    app.add_handler(reply_conv_handler)      # محادثة الرد على الرسائل

    # --- استقبال إجابات الطلاب ---
    app.add_handler(CallbackQueryHandler(receive_answer, pattern=r"^a:"))  # تغيير النمط ليطابق الصيغة الجديدة

    # --- ربط وظائف الرسائل ---
    app.add_handler(CallbackQueryHandler(show_user_messages, pattern=r"^show_msgs:"))
    app.add_handler(CallbackQueryHandler(back_to_users_list, pattern=r"^back_to_users$"))
    app.add_handler(CallbackQueryHandler(delete_message, pattern=r"^delete_msg:"))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
        handle_user_message
    ))
    app.add_handler(CommandHandler("messages", list_messages))

    # --- معالج إلغاء عام إضافي ---
    app.add_handler(CommandHandler('cancel', cancel))

    # تشغيل البوت
    logger.info("Starting bot...")
    app.run_polling()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
    # --- معالج إلغاء عام إضافي ---
    app.add_handler(CommandHandler('cancel', cancel))

    # تشغيل البوت
    logger.info("Starting bot...")
    app.run_polling()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
