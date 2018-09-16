#!/usr/bin/env python3

"""
    Telegram bot that uses api.dortos.ru to work!
"""

import copy
import json
import locale
import logging
import os
# from pprint import pprint
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import postgresql
from telegram import (ForceReply, InlineKeyboardButton,
                      InlineKeyboardMarkup, ParseMode)
from telegram.error import TimedOut
from telegram.ext import (CallbackQueryHandler, CommandHandler, Filters,
                          MessageHandler, RegexHandler, Updater)

import kbd
import strings

logging.basicConfig(format='%(asctime)s - %(name)s - '
                           '%(levelname)s - %(message)s',
                    level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def load_config() -> dict:
    """
    Load configuration file from `~/.config/dortosbot/config.json`
    Returns new dictionary with login and password for DB, and Bot Token
    """
    path = os.path.expanduser("~/.config/dortosbot/config.json")
    if not os.path.isfile(path):
        print("Configuration file {} is not found!\n".format(path) +
              "You MUST fill it with 6 values: "
              "host,port,login,password,db,token\n"
              "    host - PostgreSQL destination host\n"
              "    port - PostgreSQL destination port\n"
              "   login - PostgreSQL login\n"
              "password - PostgreSQL password\n"
              "      db - PostgreSQL database\n"
              "   token - Telegram Bot Api token")
        exit(1)
    with open(path) as config_file:
        config_str = config_file.read()
    return json.loads(config_str)


def check_institute(inst_id: int):
    """
    Checks if an institute exists in database, adds it there if not
    """
    inst_count = PGSQLDB.prepare('SELECT COUNT(id) FROM institute '
                                 'WHERE id=$1::integer')\
                        .first(inst_id)
    if inst_count != 0:
        return
    institutes = get_json("https://api.dortos.ru/v2/institute/get")
    for inst in institutes:
        if int(inst["ID"]) == inst_id:
            def datestr_as_date(value: str) -> date:
                return (value
                        .strptime(value, "%Y-%m-%d")
                        .date())
            date_start = datestr_as_date(inst["date_start"])
            date_end = datestr_as_date(inst["date_end"])
            PGSQLDB.prepare("INSERT INTO institute VALUES"
                            "($1::integer,$2::varchar,"
                            "$3::date,$4::date)")(
                                    int(inst["ID"]),
                                    inst["name"],
                                    date_start,
                                    date_end)
            break


def update_chat_week(chat_id: int, current_week: date=None) -> date:
    """
    Updates chat current_week. If second lesson is None, automatically
 selects today
    """
    if current_week is None:
        current_week = date.today()
        if current_week.weekday() == 6:
            current_week += timedelta(days=1)
        current_week -= timedelta(days=current_week.weekday())
    print("updating {} up to {}".format(chat_id, current_week))
    PGSQLDB.prepare("UPDATE chat SET week=$2::date WHERE id=$1::bigint")(
            chat_id,
            current_week)
    return current_week


def check_chat(chat_id: int, current_week: date=None) -> None:
    """
    Checks if an chat exists in database, adds it there if not
    """
    if current_week is None:
        current_week = date.today()
        if current_week.weekday() == 6:
            current_week += timedelta(days=1)
        current_week -= timedelta(days=current_week.weekday())
    chat_count = PGSQLDB.prepare("SELECT COUNT(id) FROM chat "
                                 "WHERE id=$1::bigint")\
                        .first(chat_id)
    if chat_count == 0:
        PGSQLDB.prepare("INSERT INTO chat(id,week) "
                        "VALUES($1::bigint,$2::date)")(
                                chat_id,
                                current_week)


def start(_, update):
    """
        Handles `/start` command
    """
    current_week = date.today()
    if current_week.weekday() == 6:
        current_week += timedelta(days=1)
    current_week -= timedelta(days=current_week.weekday())
    if len(update.message.text) != 6:
        argument = update.message.text[7:]
        authinfo = get_json("https://api.dortos.ru/v2/user/"
                            "auth?login={}".format(argument))[0]

        group_id = authinfo["id_group"]
        group_count = PGSQLDB.prepare('SELECT COUNT(id) FROM "group" '
                                      'WHERE id=$1::bigint')\
                             .first(int(group_id))
        if group_count == 0:
            group_info = get_json("https://api.dortos.ru/v2/groups/"
                                  "getById?id_group={}"
                                  .format(group_id))[0]
            check_institute(int(group_info["id_inst"]))

            PGSQLDB.prepare('INSERT INTO "group" VALUES '
                            '($1::bigint,$2::integer,$3::varchar)')(
                                    int(group_info["ID"]),
                                    int(group_info["id_inst"]),
                                    str(group_info["name_group"]))
            users_count = PGSQLDB.prepare('SELECT COUNT(guid) FROM "user" '
                                          'WHERE guid=$1::varchar')\
                                 .first(authinfo["GUID"])
        if users_count == 0:
            PGSQLDB.prepare('INSERT INTO "user" VALUES '
                            '($1::varchar,$2::varchar,$3::varchar,$4::varchar,'
                            ' $5::bigint,$6::smallint,$7::timestamp)')(
                                    authinfo["GUID"],
                                    argument,
                                    authinfo["first_name"],
                                    authinfo["last_name"],
                                    int(authinfo["id_group"]),
                                    int(authinfo["id_role"]),
                                    datetime.now())
        else:
            PGSQLDB.prepare('UPDATE "user" SET '
                            'login=$2::varchar,first_name=$3::varchar,'
                            'last_name=$4::varchar,group_id=$5::bigint'
                            'role=$6::smallint,update_time=$7::timestamp '
                            'WHERE guid=$1::varchar')(
                                    authinfo["GUID"],
                                    argument,
                                    authinfo["first_name"],
                                    authinfo["last_name"],
                                    int(authinfo["id_group"]),
                                    int(authinfo["id_role"]),
                                    datetime.now())

        chat_count = PGSQLDB.prepare("SELECT COUNT(id) FROM chat "
                                     "WHERE id=$1::bigint")\
                            .first(update.message.chat.id)
        if chat_count == 0:
            PGSQLDB.prepare("INSERT INTO chat VALUES"
                            "($1::bigint,$2::date,$3::varchar,$4::bigint)")(
                                    update.message.chat.id,
                                    current_week,
                                    authinfo["GUID"],
                                    int(authinfo["id_group"]))
        else:
            PGSQLDB.prepare("UPDATE chat SET week=$2::date,guid=$3::varchar "
                            "WHERE id=$1::bigint")(
                                    update.message.chat.id,
                                    current_week,
                                    authinfo["GUID"])
    else:
        check_chat(update.message.chat.id, current_week)
        update_chat_week(update.message.chat.id, current_week)
    reply_markup = InlineKeyboardMarkup(kbd.START_KEYBOARD)
    update.message.reply_text("Выберите пункт меню", reply_markup=reply_markup)


def home(bot, query):
    """
        Handles 'В главное меню' and 'Назад' buttons
    """
    reply_markup = InlineKeyboardMarkup(kbd.START_KEYBOARD)
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          reply_markup=reply_markup,
                          text="Выберите пункт меню",
                          parse_mode=ParseMode.MARKDOWN)


def get_request(url: str) -> str:
    """
        Download data by `url`
    """
    return urllib.request.urlopen(url).read().decode()


def get_json(url: str) -> dict:
    """
        Download data by `url` and parse json
    """
    return json.loads(get_request(url))


def timetable_handler(bot, query):
    """
        Handles 'Расписание' button
    """
    current_keyboard = copy.deepcopy(kbd.DAYS_KEYBOARD)
    chat = PGSQLDB.prepare("SELECT week,group_id FROM chat "
                           "WHERE id=$1::bigint")\
                  .first(query.message.chat_id)
    current_week = chat["week"]
    if current_week.weekday() == 6:
        current_week += timedelta(days=1)
    if "_" in query.data:
        # May be prev/next or weekday
        parameter = query.data[10:]
        if parameter == "prev":
            current_week -= timedelta(days=7)
            PGSQLDB.prepare("UPDATE chat SET week=$1::date "
                            "WHERE id=$2::bigint")(
                                    current_week,
                                    query.message.chat_id)
        elif parameter == "next":
            current_week += timedelta(days=7)
            PGSQLDB.prepare("UPDATE chat SET week=$1::date "
                            "WHERE id=$2::bigint")(
                                    current_week,
                                    query.message.chat_id)
        else:
            current_week -= timedelta(days=current_week.weekday())
            current_week += timedelta(days=int(parameter))
    else:
        # Happens only if user just selected this button
        # So I want to he get timetable for today
        current_week = update_chat_week(query.message.chat_id)
        current_week += timedelta(days=date.today().weekday())
        if current_week.weekday() == 6:
            current_week -= timedelta(days=6)
    if chat["group_id"] is None:
        # group is not selected
        search_handler(bot, query)
        return
    else:
        group_id = chat["group_id"]

    current_weekday = current_week.weekday()
    current_keyboard[0][current_weekday] = InlineKeyboardButton(
        "*{}*".format(kbd.DAYS_KEYBOARD[0][current_weekday].text),
        callback_data=kbd.DAYS_KEYBOARD[0][current_weekday].callback_data
    )
    reply_markup = InlineKeyboardMarkup(current_keyboard)
    request_str = "https://api.dortos.ru/v2/groups/"\
                  "getById?id_group=%d" % (group_id)
    group_name = get_json(request_str)[0]["name_group"]
    request_str = "https://api.dortos.ru/v2/timetable/get?"\
                  "date_start={0}&date_end={0}&group_id={1}"\
                  .format(current_week, group_id)
    timetable = get_json(request_str)
    reply_text = "👥 *{}*\n📅 *{} {}*\n\n".format(
            group_name,
            current_week.day,
            strings.MONTHS[current_week.month-1])
    reply_text += parse_timetable(timetable)
    bot.answer_callback_query(callback_query_id=query.id,
                              show_alert=False)
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          reply_markup=reply_markup,
                          text=reply_text,
                          parse_mode=ParseMode.MARKDOWN)


def parse_additional_lesson_info(lesson: map) -> str:
    """
        Parse lesson type, cabinet or teacher from lesson, if they are exists
    """
    tmp = ""
    if ("lesson" in lesson) and (lesson["lesson"] != ""):
        tmp += "{} ".format(lesson["lesson"])
    if ("cab" in lesson) and (lesson["cab"] != ""):
        tmp += "{} ".format(lesson["cab"])
    if ("prepod" in lesson) and (lesson["prepod"] != ""):
        tmp += "{}".format(lesson["prepod"])
    return tmp


def parse_timetable(timetable: list) -> str:
    """
        Parse whole timetable and return it's string representation
    """
    tmp = ""
    for lesson in timetable:
        if not lesson.get("printed", False):
            if lesson["id_sub_group"] == '0':
                tmp += "*{}⃣ пара {} - {} {}*\n".format(lesson["time_id"],
                                                       lesson["time_on"][:-3],
                                                       lesson["time_off"][:-3],
                                                       lesson["name"])
                tmp += "{}\n\n".format(parse_additional_lesson_info(lesson))
            else:
                this_lessons = [lesson]
                for this_lesson in timetable:
                    if ((lesson != this_lesson) and
                       (lesson["day"] == this_lesson["day"]) and
                       (lesson["time_id"] == this_lesson["time_id"])):
                        this_lessons.append(this_lesson)
                if len(this_lessons) == 1:
                    tmp += "*{}⃣ пара {} - {} {} подгруппа {}*\n".format(
                            lesson["time_id"],
                            lesson["time_on"][:-3],
                            lesson["time_off"][:-3],
                            lesson["id_sub_group"],
                            lesson["name"])
                    tmp += "{}\n\n".format(
                            parse_additional_lesson_info(this_lesson))
                else:
                    tmp += "*{}⃣ пара {} - {}*\n".format(
                            lesson["time_id"],
                            lesson["time_on"][:-3],
                            lesson["time_off"][:-3])
                    for this_lesson in this_lessons:
                        tmp += "*{} подгруппа {}* ".format(
                                this_lesson["id_sub_group"],
                                this_lesson["name"])
                        tmp += "{}\n".format(
                                parse_additional_lesson_info(this_lesson))
                        this_lesson["printed"] = True
                    tmp += "\n"
    return tmp


def tasks_handler(bot, query):
    """
        Handles "Задания" button
    """
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          text="В процессе разработки!",
                          reply_markup=kbd.HOME_MARKUP)


def profile_handler(bot, query):
    """
        Handles "Профиль" button
    """
    response = PGSQLDB.prepare('SELECT "user".first_name, "user".last_name, '
                               '"user".role,"group".name as group_name, '
                               'institute.name AS inst_name '
                               'FROM ((chat INNER JOIN "user" '
                               'ON "user".guid=chat.guid) '
                               'INNER JOIN "group" '
                               'ON "user".group_id="group".id) '
                               'INNER JOIN institute '
                               'ON institute.id="group".inst_id '
                               'WHERE chat.id=$1::bigint')\
                      .first(query.message.chat_id)
    if response is None:
        # group is not selected
        bot.send_message(text=('Вы не зарегистрировались в боте!\n'
                               'Для регистрации необходимо авторизоваться '
                               'на сайте https://dortos.ru и нажать на кнопку '
                               'Bot сверху\n'
                               'Откроется приложение на этом чате '
                               'с кнопкой Старт внизу\n'
                               'Нажмите её, и регистрация будет завершена!'),
                         chat_id=query.message.chat_id,
                         reply_markup=kbd.HOME_MARKUP)
        return
    reply = """Вы авторизованы как {} {}
{} {} {}""".format(response["first_name"],
                   response["last_name"],
                   strings.ROLES[response["role"]],
                   response["group_name"],
                   response["inst_name"])
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          text=reply,
                          reply_markup=kbd.HOME_MARKUP)


def search_handler(bot, query):
    """
        Handles "Поиск групп" button
    """
    bot.delete_message(chat_id=query.message.chat_id,
                       message_id=query.message.message_id)
    bot.send_message(chat_id=query.message.chat_id,
                     text=strings.SEARCH_STRING,
                     reply_markup=ForceReply(force_reply=True))


def button(bot, update):
    """
        Main button handler
    """
    query = update.callback_query
    check_chat(query.message.chat_id)
    if query.data.startswith("timetable"):
        timetable_handler(bot, query)
    elif query.data.startswith("tasks"):
        tasks_handler(bot, query)
    elif query.data.startswith("profile"):
        profile_handler(bot, query)
    elif query.data.startswith("search"):
        search_handler(bot, query)
    elif query.data.startswith("home"):
        home(bot, query)


def select_group(group_id: int, chat_id: int):
    """
        Updates `chat.group_id` field of `chat_id`
    """
    PGSQLDB.prepare("UPDATE chat SET group_id=$1::bigint WHERE id=$2::bigint")(
            group_id,
            chat_id)


def regex(bot, update):
    """
        Handler for /{group_id} messages
    """
    response = get_json("https://api.dortos.ru/v2/groups/"
                        "getById?id_group=%s" % (update.message.text[1:]))
    if len(response) == 0:
        bot.send_message(chat_id=update.message.chat.id,
                         text="Выбранной группы не существует!",
                         reply_markup=kbd.HOME_MARKUP)
    else:
        select_group(int(update.message.text[1:]), update.message.chat.id)
        bot.send_message(chat_id=update.message.chat.id,
                         text="Выбрана группа {}".format(
                             response[0]["name_group"]),
                         reply_markup=kbd.HOME_MARKUP)


def group_search(bot, update):
    """
        Handler for search query
    """
    if update.message.reply_to_message.text == strings.SEARCH_STRING:
        search_results = get_json("https://api.dortos.ru/v2/groups/"
                                  "search?q={}".format(
                                      urllib.parse.quote_plus(
                                          update.message.text)))
        if len(search_results) == 1:
            select_group(int(search_results[0]["ID"]), update.message.chat.id)
            bot.send_message(chat_id=update.message.chat.id,
                             text="Выбрана группа {}".format(
                                 search_results[0]["name_group"]),
                             reply_markup=kbd.HOME_MARKUP)
            return
        if len(search_results) == 0:
            bot.send_message(chat_id=update.message.chat.id,
                             text="По вашему запросу ничего не найдено",
                             reply_markup=kbd.HOME_MARKUP)
            return
        reply = "Вот результаты поиска по \"{}\"\n".format(update.message.text)
        reply += "Выберите нужную группу\n\n"
        for result in search_results:
            reply += "/{} {}\n".format(result["ID"], result["name_group"])
        bot.send_message(
                chat_id=update.message.chat.id,
                text=reply,
                reply_markup=kbd.HOME_MARKUP)


def error(_, update, err):
    """
        Error handler
    """
    if not isinstance(err, TimedOut):
        LOGGER.warning('Update "%s" caused error "%s"', update, err)


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
    locale.resetlocale()

    CONFIG = load_config()
    global PGSQLDB
    CONN_STR = "pq://{}:{}@{}:{}/{}?client_encoding='utf-8'".format(
            CONFIG["login"],
            CONFIG["password"],
            CONFIG["host"],
            CONFIG["port"],
            CONFIG["db"])
    PGSQLDB = postgresql.open(CONN_STR)

    UPDATER = Updater(CONFIG["token"])
    UPDATER.dispatcher.add_handler(CommandHandler("start", start))
    UPDATER.dispatcher.add_handler(CallbackQueryHandler(button))
    UPDATER.dispatcher.add_handler(RegexHandler(r'\/\d+', regex))
    UPDATER.dispatcher.add_handler(MessageHandler(Filters.text & Filters.reply,
                                                  group_search))
    UPDATER.dispatcher.add_error_handler(error)
    UPDATER.start_polling()
    UPDATER.idle()
