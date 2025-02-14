import telebot
from telebot import types
import sqlite3
import datetime
import io
import matplotlib
matplotlib.use('Agg')  # Устанавливаем бэкенд Agg
import matplotlib.pyplot as plt

# Инициализация бота
bot_api_key = "7794911342:AAGKwLs3DfpAt8r9eKSFzrzriM0zYIr75Ys"
bot = telebot.TeleBot(bot_api_key)

# Подключение к базе данных
conn = sqlite3.connect("finance_bot.db", check_same_thread=False)

# Создание таблиц, если их нет
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    group_id INTEGER,
                    amount REAL,
                    category TEXT,
                    type TEXT,
                    date TEXT
                )''')
conn.commit()
cursor = conn.cursor()
# Создание таблицы групп
cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    password TEXT,
    owner_id INTEGER
)''')
conn.commit()
cursor = conn.cursor()
# Создание таблицы пользователей 
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    group_id INTEGER,
                    FOREIGN KEY (group_id) REFERENCES groups(group_id)
                )''')
conn.commit()

# Таблица базовых категорий
cursor.execute('''
CREATE TABLE IF NOT EXISTS base_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,  -- "income" или "expense"
    name TEXT UNIQUE
)
''')

# Таблица выбранных категорий
cursor.execute('''CREATE TABLE IF NOT EXISTS selected_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    group_id INTEGER,
    name TEXT,
    type TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (group_id) REFERENCES groups(group_id)
)''')
conn.commit()


# Категории доходов
INCOME_CATEGORIES = ["Зарплата", "Подарки", "Прочее"]

# Категории расходов
CATEGORIES = ["Продукты", "Развлечения", "Проезд", "Бытовая химия", "Налоги", "Одежда",
              "Жильё", "Подписки", "Учёба", "Праздники", "Внеплановые"]

# категории, доступные пользователю
BASE_CATEGORIES = {
    "income": ["Зарплата", "Подарки", "Бизнес", "Другое"],
    "expense": ["Продукты", "Развлечения", "Проезд", "Бытовая химия", "Налоги", "Одежда", "Жильё", "Подписки", "Учёба", "Праздники", "Внеплановые"]
}

#Кнопки главного меню
MENU_BUTTONS = ["Добавить расход", "Добавить доход", "Статистика", "Справка"]

# Типы транзакций
TRANSACTION_TYPES = ["Расходы", "Доходы"]

# Типы статистики
STATISTIC_TYPES = ["Общая", "По категориям", "Мои расходы", "Мои доходы"]

# Виды периода для просмотра статистики
PERIOD_TYPES = ["Сутки", "Неделя", "Месяц", "Год", "Всё время"]

# Виды периода для просмотра всех поступлений, или трат
IN_OR_EX_PERIOD_TYPES = ["За неделю", "За 2 недели", "За месяц", "За всё время"]

for category_type, categories in BASE_CATEGORIES.items():
    for category_name in categories:
        cursor.execute("INSERT OR IGNORE INTO base_categories (type, name) VALUES (?, ?)", (category_type, category_name))
    conn.commit()

# Создание клавиатуры
def create_reply_keyboard(buttons, need_back_button=True, row_width = 1):
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=row_width)
    keyboard_buttons = []
    for button in buttons:
        keyboard_buttons.append(button)
    keyboard.add(*keyboard_buttons)
    if need_back_button:
        keyboard.add(types.KeyboardButton("Назад"))
    return keyboard

# Функция для главного меню
def get_main_menu():
    keyboard = create_reply_keyboard(MENU_BUTTONS,False, 2)
    return keyboard

def get_categories(user_id, category_type):
    cursor = conn.cursor()
    # Проверяем, состоит ли пользователь в группе
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None

    if group_id:
        # Получаем категории группы
        cursor.execute(
            "SELECT name FROM selected_categories WHERE group_id=? AND type=?",
            (group_id, category_type)
        )
    else:
        # Получаем категории пользователя
        cursor.execute(
            "SELECT name FROM selected_categories WHERE user_id=? AND type=?",
            (user_id, category_type)
        )

    categories = [row[0] for row in cursor.fetchall()]
    return categories

# Выбор категории для добавления расхода/дохода
def choose_category(message, trans_type):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return

    categories = get_categories(message.from_user.id, trans_type)
    if not categories:
        bot.send_message(message.chat.id, "Список категорий пуст. Добавьте новые категории.")
        return

    if message.text not in categories:
        bot.send_message(
            message.chat.id,
            "Пожалуйста, выберите категорию из списка.",
            reply_markup=create_reply_keyboard(categories, True, 2)
        )
        bot.register_next_step_handler(message, choose_category, trans_type)
        return

    bot.send_message(message.chat.id, "Введите сумму:")
    bot.register_next_step_handler(message, enter_amount, trans_type, message.text)

def notify_group_members(group_id, transaction_details):
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE group_id=?", (group_id,))
    members = cursor.fetchall()
    for member in members:
        member_id = member[0]
        bot.send_message(member_id, transaction_details)

# Обработчик ввода суммы
def enter_amount(message, trans_type, category):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        cursor = conn.cursor()
        
        # Проверяем, состоит ли пользователь в группе
        cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
        group = cursor.fetchone()
        group_id = group[0] if group and group[0] else None
        
        # Добавляем транзакцию
        cursor.execute(
            "INSERT INTO transactions (user_id, group_id, amount, category, type, date) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, group_id, amount, category, trans_type, datetime.date.today().isoformat())
        )
        conn.commit()
        
        bot.send_message(user_id, "Запись успешно добавлена!", reply_markup=get_main_menu())
        if group_id:
            notify_group_members(group_id, f"Новая транзакция: {amount} руб. ({category})")
    
    except ValueError:
        bot.send_message(message.chat.id, "Введите корректную сумму.")
        bot.register_next_step_handler(message, enter_amount, trans_type, category)

# Создание кругового графика
def generate_pie_chart(data, labels, title):
    # Создаем график
    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        data,
        autopct='%1.1f%%',
        startangle=90,
        textprops={'color': "w"}
    )
    ax.set_title(title)

    # Добавляем легенду
    legend_labels = [
        f"{label}: {'{:,.2f}'.format(value).replace(',', ' ')} руб. ({(value / sum(data)) * 100:.1f}%)"
        for label, value in zip(labels, data)
    ]
    ax.legend(wedges, legend_labels, title="Категории", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))

    # Сохраняем график в буфер
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches='tight') 
    img.seek(0)
    plt.close(fig)

    return img

# проверка и обработка выбранной категории для вывода статистики
def choose_statistics_type(message):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return
    user_id = message.from_user.id
    if message.text not in STATISTIC_TYPES:
        bot.send_message(message.chat.id, "Выберите тип статистики из списка.")
        bot.register_next_step_handler(message, choose_statistics_type)
        return

    if message.text == "Общая":
        # Показываем клавиатуру для выбора периода
        bot.send_message(message.chat.id, "Выберите период:", reply_markup=create_reply_keyboard(PERIOD_TYPES, True, 2))
        bot.register_next_step_handler(message, show_general_statistics)

    elif message.text == "По категориям":
        # Показываем клавиатуру для выбора типа транзакций
        bot.send_message(message.chat.id, "Выберите тип транзакций:", reply_markup=create_reply_keyboard(TRANSACTION_TYPES, True, 1))
        bot.register_next_step_handler(message, choose_category_statistics_type)
    
    elif message.text == "Мои расходы":
        bot.send_message(message.chat.id, "Выберите период:", reply_markup=create_reply_keyboard(IN_OR_EX_PERIOD_TYPES, True, 2))
        bot.register_next_step_handler(message, process_period_selection, "expense")

    elif message.text == "Мои доходы":
        bot.send_message(message.chat.id, "Выберите период:", reply_markup=create_reply_keyboard(IN_OR_EX_PERIOD_TYPES, True, 2))
        bot.register_next_step_handler(message, process_period_selection, "income")

# Показать статистику по категориям за выбранный период с графиком
def show_category_statistics(message, transaction_type):
    if message.text == "Назад":
        message.text = "По категориям"
        choose_statistics_type(message)
        return

    user_id = message.from_user.id

    # Определяем фильтр даты и формат временной оси
    if message.text == "Неделя":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=7)).isoformat()}'"
        time_format = "%d.%m"  # Дни для недельной статистики
    elif message.text == "Месяц":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=30)).isoformat()}'"
        time_format = "%U"  # Недели для месячной статистики (номер недели)
    elif message.text == "Год":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=365)).isoformat()}'"
        time_format = "%b"  # Месяцы для годовой статистики (сокращенные названия месяцев)
    elif message.text == "Всё время":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=100000)).isoformat()}'"
        time_format = "%Y"  # Года для статистики за всё время
    else:
        bot.send_message(message.chat.id, "Выберите период из списка.")
        bot.register_next_step_handler(message, show_category_statistics, transaction_type)
        return

    cursor = conn.cursor()
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None
    # Получаем данные по категориям и датам
    if group_id:
        cursor.execute(f"""
            SELECT category, date, SUM(amount) 
            FROM transactions 
            WHERE group_id=? AND type=? AND {date_filter}
            GROUP BY category, date
        """, (group_id, transaction_type))
    else:
        cursor.execute(f"""
            SELECT category, date, SUM(amount) 
            FROM transactions 
            WHERE user_id=? AND type=? AND {date_filter}
            GROUP BY category, date
        """, (user_id, transaction_type))
    raw_data = cursor.fetchall()
    conn.commit()

    if not raw_data:
        bot.send_message(message.chat.id, f"За выбранный период ({message.text}) нет данных.", reply_markup=get_main_menu())
        return

    # Группируем данные по категориям
    categories = {}
    for row in raw_data:
        category, date, amount = row
        formatted_date = datetime.datetime.strptime(date, "%Y-%m-%d").strftime(time_format)
        if category not in categories:
            categories[category] = {}
        categories[category][formatted_date] = categories[category].get(formatted_date, 0) + amount

    # Формируем списки для графика
    all_dates = sorted(set(date for data in categories.values() for date in data.keys()))
    category_labels = list(categories.keys())
    values_by_category = []

    for category in category_labels:
        values = [categories[category].get(date, 0) for date in all_dates]
        values_by_category.append(values)

    # Генерация графика
    img = generate_bar_chart_with_legend(all_dates, category_labels, values_by_category, transaction_type, message.text)

    # Отправка графика
    bot.send_photo(message.chat.id, img, caption=f"📊 Статистика {transaction_type.lower()} по категориям")
    bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())

# Создание столбчатой диаграммы с легендой
def generate_bar_chart_with_legend(dates, categories, values, transaction_type, period):
    fig, ax = plt.subplots(figsize=(12, 8))

    # Определяем цвета для каждой категории
    colors = plt.cm.tab10.colors  # Используем 10 различных цветов
    bar_width = 0.8 / len(categories)  # Ширина столбца для каждой категории

    # Создаем столбцы для каждой категории
    for i, category in enumerate(categories):
        positions = [x + i * bar_width for x in range(len(dates))]
        ax.bar(
            positions,
            values[i],
            width=bar_width,
            label=category,
            color=colors[i % len(colors)]
        )

    # Настройка осей
    ax.set_title(f"{transaction_type.capitalize()} за {period.lower()}")
    ax.set_xlabel("Период")
    ax.set_ylabel("Сумма (руб.)")
    ax.set_xticks([x + (len(categories) * bar_width) / 2 - bar_width / 2 for x in range(len(dates))])
    ax.set_xticklabels(dates, rotation=45, ha="right")

    # Добавляем легенду с суммами и процентами
    total_sum = sum(sum(category_values) for category_values in values)
    legend_labels = []
    for i, category in enumerate(categories):
        category_total = sum(values[i])
        percentage = (category_total / total_sum) * 100 if total_sum > 0 else 0
        legend_labels.append(
            f"{category}: {'{:,.2f}'.format(category_total).replace(',', ' ')} руб. ({percentage:.1f}%)"
        )

    ax.legend(legend_labels, title="Категории", loc="upper left", bbox_to_anchor=(1, 1))
    ax.grid(axis="y")

    # Сохранение графика в буфер
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches='tight')
    img.seek(0)
    plt.close(fig)

    return img

def show_general_statistics(message):
    if message.text == "Назад":
        show_statistics_menu(message)
        return

    user_id = message.from_user.id
    cursor = conn.cursor()

    # Проверяем, состоит ли пользователь в группе
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None

    # Определяем фильтр даты
    if message.text == "Сутки":
        date_filter = f"date = '{datetime.date.today().isoformat()}'"
    elif message.text == "Неделя":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=7)).isoformat()}'"
    elif message.text == "Месяц":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=30)).isoformat()}'"
    elif message.text == "Год":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=365)).isoformat()}'"
    elif message.text == "Всё время":
        date_filter = f"date >= '{(datetime.date.today() - datetime.timedelta(days=100000)).isoformat()}'"
    else:
        bot.send_message(message.chat.id, "Выберите период из списка.", reply_markup=get_main_menu())
        return

    # Формируем запрос для получения данных
    if group_id:
        income_query = f"SELECT SUM(amount) FROM transactions WHERE group_id=? AND type='income' AND {date_filter}"
        expense_query = f"SELECT SUM(amount) FROM transactions WHERE group_id=? AND type='expense' AND {date_filter}"
        category_query = f"""
        SELECT category, type, SUM(amount) 
        FROM transactions 
        WHERE group_id=? AND {date_filter} 
        GROUP BY category, type
        """
        query_params = (group_id,)
    else:
        income_query = f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='income' AND {date_filter}"
        expense_query = f"SELECT SUM(amount) FROM transactions WHERE user_id=? AND type='expense' AND {date_filter}"
        category_query = f"""
        SELECT category, type, SUM(amount) 
        FROM transactions 
        WHERE user_id=? AND {date_filter} 
        GROUP BY category, type
        """
        query_params = (user_id,)

    # Получаем сумму доходов и расходов
    cursor.execute(income_query, query_params)
    total_income = cursor.fetchone()[0] or 0
    cursor.execute(expense_query, query_params)
    total_expense = cursor.fetchone()[0] or 0

    # Форматируем числа
    total_income_formatted = "{:,.2f}".format(total_income).replace(",", " ")
    total_expense_formatted = "{:,.2f}".format(total_expense).replace(",", " ")

    # Получаем данные по категориям
    cursor.execute(category_query, query_params)
    category_data = cursor.fetchall()
    conn.commit()

    if not category_data:
        bot.send_message(
            message.chat.id,
            f"За выбранный период ({message.text}) нет данных.",
            reply_markup=get_main_menu()
        )
        return

    # Разделяем данные на доходы и расходы
    income_data = [(row[0], row[2]) for row in category_data if row[1] == 'income']
    expense_data = [(row[0], row[2]) for row in category_data if row[1] == 'expense']

    # Генерация графика
    all_data = income_data + expense_data
    labels = [f"{row[0]} ({'Доход' if row in income_data else 'Расход'})" for row in all_data]
    values = [row[1] for row in all_data]

    img = generate_pie_chart(values, labels, f"Финансы за {message.text}")

    # Отправка графика
    bot.send_photo(
        message.chat.id,
        img,
        caption=f"📊 Доход: {total_income_formatted} руб.\n💸 Расход: {total_expense_formatted} руб."
    )
    bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())

# Выбор категории для вывода статистики (расходы, или доходы)
def choose_category_statistics_type(message):
    if message.text == "Назад":
        show_statistics_menu(message)
        return

    if message.text not in TRANSACTION_TYPES:
        bot.send_message(message.chat.id, "Выберите тип транзакций из списка.")
        bot.register_next_step_handler(message, choose_category_statistics_type)
        return

    transaction_type = "expense" if message.text == "Расходы" else "income"

    # Показываем клавиатуру для выбора периода
    bot.send_message(message.chat.id, "Выберите период:", reply_markup=create_reply_keyboard(PERIOD_TYPES[1:], True, 1))
    bot.register_next_step_handler(message, show_category_statistics, transaction_type)

# Сохранение группы    
def set_group_name(message):
    group_name = message.text
    user_id = message.from_user.id
    cursor = conn.cursor()

    cursor.execute("SELECT group_id FROM groups WHERE name=?", (group_name,))
    group = cursor.fetchone()
    if group_name.startswith("/"):
        bot.send_message(user_id, "Недопустимое название группы! Попробуйте другое.")
        return

    if group:
        bot.send_message(user_id, "Группа с таким названием уже существует! Попробуйте другое.")
        return

    bot.send_message(user_id, "придумайте пароль для подключения к группе:")
    bot.register_next_step_handler(message, set_group_password, group_name)

# Задать пароль для группы при создании
def set_group_password(message, group_name):
    password = message.text
    user_id = message.from_user.id
    cursor = conn.cursor()

    # Создаем новую группу с паролем и владельцем
    cursor.execute("INSERT INTO groups (name, password, owner_id) VALUES (?, ?, ?)", (group_name, password, user_id))
    conn.commit()

    # Получаем ID созданной группы
    cursor.execute("SELECT group_id FROM groups WHERE name=?", (group_name,))
    group_id = cursor.fetchone()[0]

    # Привязываем пользователя к группе
    cursor.execute("UPDATE users SET group_id=? WHERE user_id=?", (group_id, user_id))
    conn.commit()

    # Копируем личные категории пользователя в группу
    cursor.execute("""
        INSERT INTO selected_categories (group_id, name, type)
        SELECT ?, name, type FROM selected_categories WHERE user_id=?
    """, (group_id, user_id))
    conn.commit()

    bot.send_message(user_id, f"Группа '{group_name}' создана!\nТеперь другие пользователи могут к ней присоединиться с помощью /join_group, введя пароль {password}")

def check_group_membership(user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    return group and group[0] is not None

# Подключение пользователя к группе, если она существует
def process_group_join(message):
    group_name = message.text
    user_id = message.from_user.id
    cursor = conn.cursor()
    # Получаем данные группы (ID и пароль)
    cursor.execute("SELECT group_id, password FROM groups WHERE name=?", (group_name,))
    group = cursor.fetchone()
    if not group:
        bot.send_message(user_id, "Такой группы не существует. Попробуйте снова.")
        return
    group_id, group_password = group
    bot.send_message(user_id, "Введите пароль для подключения к группе:")
    bot.register_next_step_handler(message, verify_group_password, group_id, group_name, group_password)

# Проверка пароля, введенного пользователем при подключении к группе
def verify_group_password(message, group_id, group_name, group_password):
    user_id = message.from_user.id
    entered_password = message.text
    if entered_password != group_password:
        bot.send_message(user_id, "Неверный пароль! Попробуйте снова.")
        return

    # Привязываем пользователя к группе
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET group_id=? WHERE user_id=?", (group_id, user_id))
    conn.commit()

     # Удаляем личные категории пользователя (если они есть)
    cursor.execute("DELETE FROM selected_categories WHERE user_id=?", (user_id,))
    conn.commit()

    # Копируем категории группы для пользователя
    cursor.execute("""
        INSERT INTO selected_categories (user_id, name, type)
        SELECT ?, name, type FROM selected_categories WHERE group_id=?
    """, (user_id, group_id))
    conn.commit()

    # Получаем информацию о пользователе
    user_info = message.from_user
    user_mention = user_info.username if user_info.username else user_info.first_name

    # Получаем ID владельца группы
    cursor.execute("SELECT owner_id FROM groups WHERE group_id=?", (group_id,))
    owner_id = cursor.fetchone()[0]

    # Отправляем уведомление владельцу группы
    if owner_id != user_id:  # Владелец не получает уведомление, если сам присоединяется
        bot.send_message(
            owner_id,
            f"✅ Пользователь [{user_mention}](tg://user?id={user_id}) присоединился к группе '{group_name}'.",
            parse_mode="Markdown"
        )

    # Отправляем сообщение пользователю
    bot.send_message(user_id, f"Вы присоединились к группе '{group_name}'!")

def update_transaction_list(obj, transaction_type, period):
    # Преобразуем период в дату начала
    if period == "За неделю":
        start_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    elif period == "За 2 недели":
        start_date = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
    elif period == "За месяц":
        start_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    elif period == "За всё время":
        start_date = "1970-01-01"
    else:
        bot.send_message(obj.chat.id, "Неизвестный период. Вернитесь в главное меню.", reply_markup=get_main_menu())
        return

    user_id = obj.from_user.id

    # Запрашиваем данные за выбранный период
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, amount, category, date FROM transactions "
        "WHERE user_id=? AND type=? AND date >= ? ORDER BY date DESC LIMIT 10",
        (user_id, transaction_type, start_date)
    )
    transactions = cursor.fetchall()
    conn.commit()

    if not transactions:
        bot.send_message(user_id, f"У вас больше нет записанных {transaction_type}ов за выбранный период.", reply_markup=get_main_menu())
        return

    # Формируем клавиатуру с актуальными данными
    keyboard = types.InlineKeyboardMarkup()
    for transaction in transactions:
        transaction_id, amount, category, date = transaction
        keyboard.add(types.InlineKeyboardButton(
            text=f"{date} - {category}: {amount}₽",
            callback_data=f"del_{transaction_type}_{transaction_id}"
        ))

    # Добавляем кнопку "Показать все", если записей больше 10
    if len(transactions) > 10:
        keyboard.add(types.InlineKeyboardButton(text="Показать все", callback_data=f"show_all_{transaction_type}_{start_date}"))

    # Добавляем кнопку "Назад"
    keyboard.add(types.InlineKeyboardButton(text="Назад", callback_data="back_to_main_menu"))

    # Отправляем обновленный список
    if hasattr(obj, 'message'):  # Если это callback query
        bot.edit_message_text(
            chat_id=obj.message.chat.id,
            message_id=obj.message.message_id,
            text=f"Ваши последние {transaction_type}ы за {period.lower()}. Нажмите, чтобы удалить:",
            reply_markup=keyboard
        )
    else:  # Если это обычное сообщение
        bot.send_message(
            chat_id=obj.chat.id,
            text=f"Ваши последние {transaction_type}ы за {period.lower()}. Нажмите, чтобы удалить:",
            reply_markup=keyboard
        )

# Определение периода для вывода списка доходов/расходов 
def process_period_selection(message, transaction_type):
    user_id = message.from_user.id
    if message.text == "Назад":
        show_statistics_menu(message)
        return
    period = message.text

    update_transaction_list(message, transaction_type, period)

def choose_category_type_to_manage(message):
    if message.text == "Назад":
        bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return
    category_type = message.text.lower()
    if category_type not in ["расходы", "доходы"]:
        bot.send_message(message.chat.id, "Выберите тип категорий из списка.", reply_markup=get_main_menu())
        return
    category_type = "expense" if category_type == "расходы" else "income"
    show_selected_categories(message, category_type)

def show_selected_categories(message, category_type):
    user_id = message.from_user.id
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None

    if group_id:
        # Пользователь в группе: получаем категории группы
        cursor.execute("""
        SELECT name FROM selected_categories 
        WHERE group_id=? AND type=?
        """, (group_id, category_type))
    else:
        # Пользователь не в группе: получаем категории пользователя
        cursor.execute("""
        SELECT name FROM selected_categories 
        WHERE user_id=? AND type=?
        """, (user_id, category_type))

    selected_categories = [row[0] for row in cursor.fetchall()]
    keyboard = create_reply_keyboard(["Добавить категорию", "Удалить категорию"], True, 1)
    bot_message = f"Ваши выбранные {category_type}:\n"
    for i in selected_categories:
        bot_message+="\n"+i
    bot.send_message(user_id, bot_message, reply_markup=keyboard)
    bot.register_next_step_handler(message, manage_selected_categories, category_type, selected_categories)

def manage_selected_categories(message, category_type, selected_categories):
    user_id = message.from_user.id
    action = message.text
    if action == "Назад":
        message.text = "back"
        manage_categories(message)
        return
    
    if action == "Добавить категорию":
        add_category(message, category_type, selected_categories)
    elif action == "Удалить категорию":
        delete_category(message, category_type, selected_categories)
    else:
        bot.send_message(user_id, "Выберите действие из списка.", reply_markup=get_main_menu())

def add_category(message, category_type, selected_categories):
    user_id = message.from_user.id
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None

    # Получаем базовые категории, которых нет в выбранных
    query = """
    SELECT name FROM base_categories 
    WHERE type=? AND name NOT IN ({})
    """.format(",".join(["?"] * len(selected_categories)))
    params = [category_type] + selected_categories

    cursor.execute(query, params)
    base_categories = [row[0] for row in cursor.fetchall()]

    keyboard = create_reply_keyboard(base_categories, False, 2)
    keyboard.add("Другое", "Назад")

    bot.send_message(user_id, "Выберите категорию для добавления:", reply_markup=keyboard)
    bot.register_next_step_handler(message, process_add_category, category_type, selected_categories, group_id)

def process_add_category(message, category_type, selected_categories, group_id):
    if message.text == "Назад":
        show_selected_categories(message, category_type)
        return
    if message.text == "Другое":
        bot.send_message(message.chat.id, "Введите название новой категории:")
        bot.register_next_step_handler(message, add_custom_category, category_type, selected_categories, group_id)
        return

    new_category = message.text
    user_id = message.from_user.id

    if group_id:
        # Добавляем категорию для группы
        cursor.execute("""
        INSERT INTO selected_categories (group_id, type, name) VALUES (?, ?, ?)
        """, (group_id, category_type, new_category))
    else:
        # Добавляем категорию для пользователя
        cursor.execute("""
        INSERT INTO selected_categories (user_id, type, name) VALUES (?, ?, ?)
        """, (user_id, category_type, new_category))

    conn.commit()
    bot.send_message(message.chat.id, f"Категория '{new_category}' добавлена!")
    show_selected_categories(message, category_type)

def add_custom_category(message, category_type, selected_categories, group_id):
    user_id = message.from_user.id
    custom_category = message.text.strip()

    if not custom_category or custom_category in ["Другое","Назад"]:
        bot.send_message(user_id, "Название категории не может быть таким. Попробуйте снова.")
        bot.register_next_step_handler(message, add_custom_category, category_type, selected_categories, group_id)
        return

    if group_id:
        cursor.execute("""
        SELECT COUNT(*) FROM selected_categories 
        WHERE group_id=? AND type=? AND name=?
        """, (group_id, category_type, custom_category))
    else:
        cursor.execute("""
        SELECT COUNT(*) FROM selected_categories 
        WHERE user_id=? AND type=? AND name=?
        """, (user_id, category_type, custom_category))

    if cursor.fetchone()[0] > 0:
        bot.send_message(user_id, f"Категория '{custom_category}' уже существует!")
        show_selected_categories(message, category_type)
        return

    # Добавляем новую категорию
    if group_id:
        cursor.execute("""
        INSERT INTO selected_categories (group_id, type, name) VALUES (?, ?, ?)
        """, (group_id, category_type, custom_category))
    else:
        cursor.execute("""
        INSERT INTO selected_categories (user_id, type, name) VALUES (?, ?, ?)
        """, (user_id, category_type, custom_category))

    conn.commit()
    bot.send_message(user_id, f"Категория '{custom_category}' успешно добавлена!")
    show_selected_categories(message, category_type)

def delete_category(message, category_type, selected_categories):
    user_id = message.from_user.id
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    group_id = group[0] if group and group[0] else None

    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for category in selected_categories:
        keyboard.add(types.KeyboardButton(category))
    keyboard.add("Назад")

    bot.send_message(user_id, "Выберите категорию для удаления:", reply_markup=keyboard)
    bot.register_next_step_handler(message, process_delete_category, category_type, group_id)

def process_delete_category(message, category_type, group_id):
    if message.text == "Назад":
        show_selected_categories(message, category_type)
        return

    category_to_delete = message.text
    user_id = message.from_user.id

    if group_id:
        # Удаляем категорию для группы
        cursor.execute("""
        DELETE FROM selected_categories 
        WHERE group_id=? AND type=? AND name=?
        """, (group_id, category_type, category_to_delete))
    else:
        # Удаляем категорию для пользователя
        cursor.execute("""
        DELETE FROM selected_categories 
        WHERE user_id=? AND type=? AND name=?
        """, (user_id, category_type, category_to_delete))

    conn.commit()
    bot.send_message(message.chat.id, f"Категория '{category_to_delete}' удалена!")
    show_selected_categories(message, category_type)



#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\ОБРАБОТЧИКИ///////////////////////////////////////////////


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    cursor = conn.cursor()
    # Добавляем пользователя в таблицу users, если его там еще нет
    cursor.execute("INSERT OR IGNORE INTO users (user_id, group_id) VALUES (?, ?)", (user_id, None))

    # Проверяем, есть ли уже выбранные категории для пользователя
    cursor.execute("SELECT COUNT(*) FROM selected_categories WHERE user_id=?", (user_id,))
    if cursor.fetchone()[0] == 0:
        # Добавляем стартовые категории для доходов
        starter_income_categories = ["Зарплата", "Другое"]
        for category in starter_income_categories:
            cursor.execute(
                "INSERT INTO selected_categories (user_id, type, name) VALUES (?, ?, ?)",
                (user_id, "income", category)
            )

        # Добавляем стартовые категории для расходов
        starter_expense_categories = [
            "Продукты", "Развлечения", "Налоги", "Одежда", "Жильё", "Внеплановые"
        ]
        for category in starter_expense_categories:
            cursor.execute(
                "INSERT INTO selected_categories (user_id, type, name) VALUES (?, ?, ?)",
                (user_id, "expense", category)
            )

    conn.commit()

    bot.send_message(user_id, "Привет! Я бот для учета доходов и расходов.\nЯ помогу тебе и твоей семье вести бюджет\nЧтобы узнать подробности, нажми на кнопку \"Справка\", или введи /help\nПриятного пользования!", reply_markup=get_main_menu())
    

@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda message: message.text=="Справка")
def help(message):
    bot.send_message(message.from_user.id,("Справка:\nТы можешь вести свой личный, или семейный бюджет, для этого тебе всего лишь надо:\n\n"
                                            "1. Определиться, хочешь ли ты вести свою статистику расходов и доходов, или же хочешь создать группу с другими пользователями и вести общий бюджет (/create_group).\n\n"
                                            "2. Чтобы начать вести статистику, рекомендую настроить для себя, или своей группы категории дохода/расхода. Ты можешь выбирать категории из списка базовых, или добавлять свои (/categories).\n\n"
                                            "3. Можешь посмотреть статистику по доходам и расходам через главное меню:\n\"Общая\" - посмотреть статистику по всем доходам и расходам,\n\"По категориям\" - посмотреть только расходы, или доходы отдельно\n\"Мои расходы\" и \"Мои доходы\" - списки с возможностью удалять добавленные доходы/расходы\n\n"
                                            "4. Если в процессе использования бота ты столкнешься с проблемами, или багами - попробуй меня перезагрузить при помощи /start, если это не помогло, напиши моему создателю: @Pavel0777\n\n"
                                            "А вот и список всех команд. Ты можешь выбрать команду, нажать по ней, и она запустится. Или можешь ввести её самостоятельно в чат:\n"
                                            "/start - запустить, или перезапустить бота.\n"
                                            "/help - список всех команд\n"
                                            "/categories - меню редактирования категорий\n"
                                            "/create_group - создать группу для ведения общего бюджета\n"
                                            "/join_group - подключиться к существующей группе\n"
                                            "/leave_group - выйти из группы, в которой вы состоите\n"
                                            "/group_info - посмотреть данные группы"
                                           )
                    )

@bot.message_handler(commands=['categories'])
def manage_categories(message):
    user_id = message.from_user.id
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add("Расходы", "Доходы", "Назад")
    bot.send_message(user_id, "Выберите тип категорий для управления:", reply_markup=keyboard)
    bot.register_next_step_handler(message, choose_category_type_to_manage)

# Обработчик кнопок главного меню
@bot.message_handler(func=lambda message: message.text in ["Добавить расход", "Добавить доход"])
def transaction_type(message):
    user_id = message.from_user.id
    if message.text == "Добавить расход":
        categories = get_categories(user_id, "expense")
        bot.send_message(user_id, "Выберите категорию:", reply_markup=create_reply_keyboard(categories, True, 2))
        bot.register_next_step_handler(message, choose_category, "expense")
    else:
        categories = get_categories(user_id, "income")
        bot.send_message(user_id, "Выберите категорию:", reply_markup=create_reply_keyboard(categories, True, 2))
        bot.register_next_step_handler(message, choose_category, "income")

# показать статистику для пользователя, или для группы
@bot.message_handler(func=lambda message: message.text == "Статистика")
def show_statistics_menu(message):
    bot.send_message(message.chat.id, "Выберите тип статистики:", reply_markup=create_reply_keyboard(STATISTIC_TYPES,True, 2))
    bot.register_next_step_handler(message, choose_statistics_type)

#Создание группы по команде
@bot.message_handler(commands=['create_group'])
def create_group(message):
    user_id = message.from_user.id
    bot.send_message(user_id, "Введите название новой группы:")
    bot.register_next_step_handler(message, set_group_name)

# Регистратор команды group_info для вывода информации о группе
@bot.message_handler(commands=['group_info'])
def show_group_info(message):
    user_id = message.from_user.id
    cursor = conn.cursor()

    # Check if the user belongs to a group
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    if not group or not group[0]:
        bot.send_message(user_id, "Вы не состоите ни в одной группе.")
        return

    group_id = group[0]

    # Check if the user is the owner of the group
    cursor.execute("SELECT name, password FROM groups WHERE group_id=? AND owner_id=?", (group_id, user_id))
    owner_group = cursor.fetchone()

    if owner_group:
        # User is the owner of the group
        group_name, group_password = owner_group
        bot.send_message(user_id, f"Информация о вашей группе:\n"
                                  f"Название: {group_name}\n"
                                  f"Пароль: {group_password}")
    else:
        # User belongs to a group but is not the owner
        cursor.execute("SELECT name FROM groups WHERE group_id=?", (group_id,))
        group_data = cursor.fetchone()

        if not group_data:
            bot.send_message(user_id, "Произошла ошибка. Группа не найдена.")
            return

        group_name = group_data[0]
        bot.send_message(user_id, f"Вы состоите в группе:\n"
                                  f"Название: {group_name}")

# Присоединение к группе по команде
@bot.message_handler(commands=['join_group'])
def join_group(message):
    user_id = message.from_user.id
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM groups")
    groups = cursor.fetchall()
    if not groups:
        bot.send_message(user_id, "Групп пока нет. Создайте свою с помощью /create_group")
        return
    bot.send_message(user_id, "Введите название группы для присоединения.")
    bot.register_next_step_handler(message, process_group_join)

# удаление/выход из группы по команде
@bot.message_handler(commands=['leave_group'])
def leave_group(message):
    user_id = message.from_user.id
    cursor = conn.cursor()

    # Проверяем, к какой группе принадлежит пользователь
    cursor.execute("SELECT group_id FROM users WHERE user_id=?", (user_id,))
    group = cursor.fetchone()
    if not group or group[0] is None:
        bot.send_message(user_id, "Вы не состоите ни в одной группе.")
        return

    group_id = group[0]

    # Получаем данные группы (название и ID владельца)
    cursor.execute("SELECT name, owner_id FROM groups WHERE group_id=?", (group_id,))
    group_data = cursor.fetchone()
    if not group_data:
        bot.send_message(user_id, "Произошла ошибка. Группа не найдена.")
        return

    group_name, owner_id = group_data

    # Получаем информацию о пользователе, который покидает группу
    user_info = message.from_user
    user_mention = user_info.username if user_info.username else user_info.first_name

    # Проверяем, является ли пользователь владельцем группы
    if owner_id == user_id:
        # Владелец удаляет группу
        try:
            # Удаляем все транзакции, связанные с группой
            cursor.execute("DELETE FROM transactions WHERE group_id=?", (group_id,))
            
            # Удаляем все категории, связанные с группой
            cursor.execute("DELETE FROM selected_categories WHERE group_id=?", (group_id,))
            
            # Удаляем всех пользователей из группы
            cursor.execute("UPDATE users SET group_id=NULL WHERE group_id=?", (group_id,))
            
            # Удаляем саму группу
            cursor.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
            
            conn.commit()
            
            bot.send_message(user_id, f"Группа '{group_name}' удалена. Вы вернулись к личному бюджету.")
        except Exception as e:
            conn.rollback()
            bot.send_message(user_id, "Произошла ошибка при удалении группы. Попробуйте позже.")
            print(f"Ошибка при удалении группы: {e}")
    else:
        # Участник покидает группу
        cursor.execute("UPDATE users SET group_id=NULL WHERE user_id=?", (user_id,))
        conn.commit()

        # Отправляем уведомление владельцу группы
        bot.send_message(
            owner_id,
            f"⚠️ Пользователь [{user_mention}](tg://user?id={user_id}) покинул группу '{group_name}'.",
            parse_mode="Markdown"
        )

        # Отправляем сообщение пользователю
        bot.send_message(user_id, f"Вы покинули группу '{group_name}' и вернулись к личному бюджету.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main_menu")
def back_to_main_menu(call):
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Главное меню", reply_markup=get_main_menu())


@bot.callback_query_handler(func=lambda call: call.data.startswith("del_"))
def delete_transaction(call):
    _, transaction_type, transaction_id = call.data.split("_")
    transaction_id = int(transaction_id)

    # Получаем текст сообщения, чтобы извлечь период
    message_text = call.message.text
    period = None

    for period_option in IN_OR_EX_PERIOD_TYPES:
        if period_option.lower() in message_text.lower():
            period = period_option
            break

    if not period:
        bot.answer_callback_query(call.id, "Не удалось определить период.")
        bot.send_message(call.message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return

    # Подтверждение удаления
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="Да", callback_data=f"confirm_del_{transaction_type}_{transaction_id}_{period}"))
    keyboard.add(types.InlineKeyboardButton(text="Нет", callback_data=f"cancel_del_{transaction_type}_{period}"))
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Вы уверены, что хотите удалить этот {transaction_type}?",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_del_"))
def confirm_delete(call):
    parts = call.data.split("_")
    if len(parts) != 5 or parts[0] != "confirm" or parts[1] != "del":
        bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.")
        bot.send_message(call.message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return

    _, _, transaction_type, transaction_id, period = parts
    try:
        transaction_id = int(transaction_id)
    except ValueError:
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID транзакции.")
        bot.send_message(call.message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return

    # Удаляем транзакцию из базы данных
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
    conn.commit()

    # Отправляем уведомление об успешном удалении
    bot.answer_callback_query(call.id, f"{transaction_type.capitalize()} удален!")

    # Обновляем список транзакций
    update_transaction_list(call, transaction_type, period)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_del_"))
def cancel_delete(call):
    # Разбираем callback_data
    parts = call.data.split("_")
    
    # Проверяем, что количество частей соответствует ожидаемому
    if len(parts) != 4 or parts[0] != "cancel" or parts[1] != "del":
        bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.")
        bot.send_message(call.message.chat.id, "Главное меню", reply_markup=get_main_menu())
        return
    
    _, _, transaction_type, period = parts
    
    # Уведомляем пользователя об отмене удаления
    bot.answer_callback_query(call.id, "Удаление отменено.")
    
    # Обновляем список транзакций
    update_transaction_list(call, transaction_type, period)


@bot.callback_query_handler(func=lambda call: call.data.startswith("show_all_"))
def show_all_transactions(call):
    parts = call.data.split("_")
    if len(parts) != 3 or parts[0] != "show" or parts[1] not in ["income", "expense"]:
        bot.answer_callback_query(call.id, "Ошибка: некорректный запрос.")
        return
    
    _, transaction_type, start_date = parts
    user_id = call.from_user.id
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, amount, category, date FROM transactions "
        "WHERE user_id=? AND type=? AND date >= ? ORDER BY date DESC",
        (user_id, transaction_type, start_date)
    )
    transactions = cursor.fetchall()
    conn.commit()

    if not transactions:
        bot.answer_callback_query(call.id, "Нет данных для показа.")
        return

    text = f"Все ваши {transaction_type} за выбранный период:\n"
    for transaction in transactions:
        transaction_id, amount, category, date = transaction
        text += f"{date} - {category}: {amount}₽\n"

    bot.answer_callback_query(call.id, "Полный список загружен.")
    bot.send_message(call.message.chat.id, text, reply_markup=get_main_menu())




# Переход в меню когда пользователь отправляет произвольное сообщение (должно быть в конце)
@bot.message_handler(func=lambda message: True)
def handle_any_message(message):
    bot.send_message(message.chat.id, "Главное меню", reply_markup=get_main_menu())

# Запуск бота
if __name__ == "__main__":
    # Запускаем бота без отправки сообщений всем пользователям
    bot.polling(none_stop=True)