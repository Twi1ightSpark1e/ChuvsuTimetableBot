from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

START_KEYBOARD = [[InlineKeyboardButton("Расписание", callback_data='timetable'),
                   InlineKeyboardButton("Задания", callback_data='tasks'),],
                  [InlineKeyboardButton("Профиль", callback_data='profile'),
                   InlineKeyboardButton("Поиск групп", callback_data='search')]]

BACK_BUTTON = InlineKeyboardButton("Назад", callback_data='home')
HOME_BUTTON = InlineKeyboardButton("В главное меню", callback_data='home')
HOME_MARKUP = InlineKeyboardMarkup([[HOME_BUTTON]])

DAYS_KEYBOARD = [[InlineKeyboardButton("ПН", callback_data='timetable_0'),
                  InlineKeyboardButton("ВТ", callback_data='timetable_1'),
                  InlineKeyboardButton("СР", callback_data='timetable_2'),
                  InlineKeyboardButton("ЧТ", callback_data='timetable_3'),
                  InlineKeyboardButton("ПТ", callback_data='timetable_4'),
                  InlineKeyboardButton("СБ", callback_data='timetable_5')],
                 [InlineKeyboardButton("Пред.неделя", callback_data='timetable_prev'),
                  BACK_BUTTON,
                  InlineKeyboardButton("След.неделя", callback_data='timetable_next')]]