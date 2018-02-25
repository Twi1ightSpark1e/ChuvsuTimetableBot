#!/bin/env python3

"""
Telegram bot that uses api.dortos.ru to work!
"""

import copy
import json
import locale
import logging
import os
#from pprint import pprint
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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
LOGGER = logging.getLogger(__name__)

"""Return new dictionary with login and password for PostgreSQL"""
def load_config() -> dict:
    """
        Load configuration file from `~/.config/dortosbot/config.json`
    """
    path = os.path.expanduser("~/.config/dortosbot/config.json")
    if not os.path.isfile(path):
        print("Configuration file {} is not found!\n".format(path) +
              "You MUST fill it with 6 values: host,port,login,password,db,token\n"\
              "    host - PostgreSQL destination host\n"\
              "    port - PostgreSQL destination port\n"\
              "   login - PostgreSQL login\n"\
              "password - PostgreSQL password\n"\
              "      db - PostgreSQL database\n"\
              "   token - Telegram Bot Api token")
        exit(1)
    with open(path) as config_file:
        config_str = config_file.read()
    return json.loads(config_str)

def check_institute(inst_id: int):
    """
        Checks if an institute exists in database, adds it there if not
    """
    inst_count = PGSQLDB.prepare('SELECT COUNT(id) FROM institute WHERE id=$1::integer')\
                        .first(inst_id)
    if inst_count == 0:
        institutes = get_json("https://api.dortos.ru/v2/institute/get")
        for inst in institutes:
            if int(inst["ID"]) == inst_id:
                date_start = datetime.strptime(inst["date_start"], "%Y-%m-%d").date()
                date_end = datetime.strptime(inst["date_end"], "%Y-%m-%d").date()
                PGSQLDB.prepare("INSERT INTO institute "\
                                "VALUES ($1::integer,$2::varchar,$3::date,$4::date)")\
                               (int(inst["ID"]),
                                inst["name"],
                                date_start,
                                date_end)
                break

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
        authinfo = get_json("https://api.dortos.ru/v2/user/auth?login={}".format(argument))[0]

        group_id = authinfo["id_group"]
        group_count = PGSQLDB.prepare('SELECT COUNT(id) FROM "group" WHERE id=$1::bigint')\
                             .first(int(group_id))
        if group_count == 0:
            group_info = get_json("https://api.dortos.ru/v2/groups/getById?id_group={}"\
                                                .format(group_id))[0]
            check_institute(int(group_info["id_inst"]))

            PGSQLDB.prepare('INSERT INTO "group" VALUES ($1::bigint,$2::integer,$3::varchar)')\
                           (int(group_info["ID"]),
                            int(group_info["id_inst"]),
                            str(group_info["name_group"]))
        users_count = PGSQLDB.prepare('SELECT COUNT(guid) FROM "user" WHERE guid=$1::varchar')\
                             .first(authinfo["GUID"])
        if users_count == 0:
            PGSQLDB.prepare('INSERT INTO "user" VALUES '\
                            '($1::varchar,$2::varchar,$3::varchar,$4::varchar,'\
                            ' $5::bigint,$6::smallint,$7::timestamp)')\
                           (authinfo["GUID"],
                            argument,
                            authinfo["first_name"],
                            authinfo["last_name"],
                            int(authinfo["id_group"]),
                            int(authinfo["id_role"]),
                            datetime.now())
        else:
            PGSQLDB.prepare('UPDATE "user" SET '\
                            'login=$2::varchar,first_name=$3::varchar,last_name=$4::varchar,'\
                            'group_id=$5::bigint,role=$6::smallint,update_time=$7::timestamp '\
                            'WHERE guid=$1::varchar')\
                           (authinfo["GUID"],
                            argument,
                            authinfo["first_name"],
                            authinfo["last_name"],
                            int(authinfo["id_group"]),
                            int(authinfo["id_role"]),
                            datetime.now())

        chat_count = PGSQLDB.prepare("SELECT COUNT(id) FROM chat WHERE id=$1::bigint")\
                            .first(update.message.chat.id)
        if chat_count == 0:
            PGSQLDB.prepare("INSERT INTO chat VALUES($1::bigint,$2::date,$3::varchar,$4::bigint)")\
                           (update.message.chat.id,
                            current_week,
                            authinfo["GUID"],
                            int(authinfo["id_group"]))
        else:
            PGSQLDB.prepare("UPDATE chat SET week=$2::date,guid=$3::varchar WHERE id=$1::bigint")\
                           (update.message.chat.id,
                            current_week,
                            authinfo["GUID"])
    else:
        chat_count = PGSQLDB.prepare("SELECT COUNT(id) FROM chat WHERE id=$1::bigint")\
                            .first(update.message.chat.id)
        if chat_count == 0:
            PGSQLDB.prepare("INSERT INTO chat(id,week) VALUES($1::bigint,$2::date)")\
                           (update.message.chat.id,
                            current_week)
        else:
            PGSQLDB.prepare("UPDATE chat SET week=$2::date WHERE id=$1::bigint")\
                           (update.message.chat.id,
                            current_week)
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
    chat = PGSQLDB.prepare("SELECT week,group_id FROM chat WHERE id=$1::bigint")\
                  .first(query.message.chat_id)
    minimal_date = chat["week"]
    current_date = max(date.today(), minimal_date)
    if current_date.weekday() == 6:
        current_date += timedelta(days=1)
    if "_" in query.data:
        parameter = query.data[10:]
        if parameter == "prev":
            current_date = minimal_date - timedelta(days=7)
            PGSQLDB.prepare("UPDATE chat SET week=$1::date WHERE id=$2::bigint")\
                           (current_date, query.message.chat_id)
        elif parameter == "next":
            current_date = minimal_date + timedelta(days=7)
            PGSQLDB.prepare("UPDATE chat SET week=$1::date WHERE id=$2::bigint")\
                           (current_date, query.message.chat_id)
        else:
            current_date -= timedelta(days=current_date.weekday())
            current_date += timedelta(days=int(parameter))
    if chat["group_id"] is None:
        #group is not selected
        search_handler(bot, query)
        return
    else:
        group_id = chat["group_id"]

    current_weekday = current_date.weekday()
    current_keyboard[0][current_weekday] = InlineKeyboardButton(
        "*{}*".format(kbd.DAYS_KEYBOARD[0][current_weekday].text),
        callback_data=kbd.DAYS_KEYBOARD[0][current_weekday].callback_data
    )
    reply_markup = InlineKeyboardMarkup(current_keyboard)
    request_str = "https://api.dortos.ru/v2/groups/getById?id_group=%d" % (group_id)
    group_name = get_json(request_str)[0]["name_group"]
    request_str = "https://api.dortos.ru/v2/timetable/get?"\
                  "date_start={0}&date_end={0}&group_id={1}".format(current_date, group_id)
    timetable = get_json(request_str)
    reply_text = "👥 *{}*\n📅 *{} {}*\n\n".format(group_name,
                                                  current_date.day,
                                                  strings.MONTHS[current_date.month-1])
    for lesson in timetable:
        if ("printed" in lesson and lesson["printed"] != True) or ("printed" not in lesson):
            if lesson["id_sub_group"] == '0':
                reply_text += "*{} пара {} - {} {}*\n".format(lesson["time_id"],
                                                              lesson["time_on"][:-3],
                                                              lesson["time_off"][:-3],
                                                              lesson["name"])
            else:
                reply_text += "*{} пара {} - {} {} подгруппа {}*\n".format(lesson["time_id"],
                                                                           lesson["time_on"][:-3],
                                                                           lesson["time_off"][:-3],
                                                                           lesson["id_sub_group"],
                                                                           lesson["name"])
            if ("lesson" in lesson) and (lesson["lesson"] != ""):
                reply_text += "{} ".format(lesson["lesson"])
            if ("cab" in lesson) and (lesson["cab"] != ""):
                reply_text += "{} ".format(lesson["cab"])
            if ("prepod" in lesson) and (lesson["prepod"] != ""):
                reply_text += "{}".format(lesson["prepod"])
            reply_text += "\n\n"
            lesson["printed"] = True
    bot.answer_callback_query(callback_query_id=query.id,
                              show_alert=False)
    print("{} executed {}".format(query.message.chat_id,
                                  query.data))
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          reply_markup=reply_markup,
                          text=reply_text,
                          parse_mode=ParseMode.MARKDOWN)

def tasks_handler(bot, query):
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          text="В процессе разработки!",
                          reply_markup=kbd.HOME_MARKUP)

def profile_handler(bot, query):
    response = PGSQLDB.prepare('SELECT "user".first_name, "user".last_name, "user".role,'\
                               '"group".name as group_name, institute.name AS inst_name '\
                               'FROM ((chat INNER JOIN "user" ON "user".guid=chat.guid) '\
                               'INNER JOIN "group" ON "user".group_id="group".id) '\
                               'INNER JOIN institute ON institute.id="group".inst_id '\
                               'WHERE chat.id=$1::bigint')\
                      .first(query.message.chat_id)
    if response is None:
        #group is not selected
        bot.send_message(text="""Вы не зарегистрировались в боте!
Для регистрации необходимо авторизоваться на сайте https://dortos.ru и нажать на кнопку с иконкой Telegram сверху
Откроется приложение на этом чате с кнопкой Старт внизу
Нажмите её, и регистрация будет завершена!""", 
                         chat_id=query.message.chat_id,
                         reply_markup=kbd.HOME_MARKUP)
        return
    reply = "Вы авторизованы как {} {}\n{} {} {}".format(response["first_name"],
                                                         response["last_name"],
                                                         strings.ROLES[response["role"]],
                                                         response["group_name"],
                                                         response["inst_name"])
    bot.edit_message_text(chat_id=query.message.chat_id,
                          message_id=query.message.message_id,
                          text=reply,
                          reply_markup=kbd.HOME_MARKUP)

def search_handler(bot, query):
    bot.delete_message(chat_id=query.message.chat_id,
                       message_id=query.message.message_id)
    bot.send_message(chat_id=query.message.chat_id,
                     text=strings.SEARCH_STRING,
                     reply_markup=ForceReply(force_reply=True))

def button(bot, update):
    query = update.callback_query
    reply_markup = InlineKeyboardMarkup(kbd.START_KEYBOARD)
    if (query.data.startswith("timetable")):
        timetable_handler(bot, query)
    elif (query.data.startswith("tasks")):
        tasks_handler(bot, query)
    elif (query.data.startswith("profile")):
        profile_handler(bot, query)
    elif (query.data.startswith("search")):
        search_handler(bot, query)
    elif (query.data.startswith("home")):
        home(bot, query)

def select_group(id: int, chatid: int):
    PGSQLDB.prepare("UPDATE chat SET group_id=$1::bigint WHERE id=$2::bigint")\
                   (id, chatid)

def regex(bot, update):
    response = get_json("https://api.dortos.ru/v2/groups/getById?id_group=%s" % (update.message.text[1:]))
    if (len(response) == 0):
        bot.send_message(chat_id=update.message.chat.id,
                         text="Выбранной группы не существует!",
                         reply_markup=kbd.HOME_MARKUP)
    else:
        select_group(int(update.message.text[1:]), update.message.chat.id)
        bot.send_message(chat_id=update.message.chat.id,
                         text="Выбрана группа {}".format(response[0]["name_group"]),
                         reply_markup=kbd.HOME_MARKUP)

def group_search(bot, update):
    if (update.message.reply_to_message.text == strings.SEARCH_STRING):
        search_results = get_json("https://api.dortos.ru/v2/groups/search?q={}".format(urllib.parse.quote_plus(update.message.text)))
        if (len(search_results) == 1):
            select_group(int(search_results[0]["ID"]), update.message.chat.id)
            bot.send_message(chat_id=update.message.chat.id,
                             text="Выбрана группа {}".format(search_results[0]["name_group"]),
                             reply_markup=kbd.HOME_MARKUP)
            return
        if (len(search_results) == 0):
            bot.send_message(chat_id=update.message.chat.id,
                             text="По вашему запросу ничего не найдено",
                             reply_markup=kbd.HOME_MARKUP)
            return
        reply = """Вот результаты поиска по \"{}\"
Выберите нужную группу

""".format(update.message.text)
        for result in search_results:
            reply += """/{} {}
""".format(result["ID"], result["name_group"])
        bot.send_message(chat_id=update.message.chat.id, text=reply, reply_markup=kbd.HOME_MARKUP)

def error(bot, update, error):
    if not isinstance(error, TimedOut):
        LOGGER.warning('Update "%s" caused error "%s"', update, error)

if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
    locale.resetlocale()

    config = load_config()
    global PGSQLDB
    PGSQLDB = postgresql.open("pq://{}:{}@{}:{}/{}?client_encoding='utf-8'".format(config["login"],
                                                                                   config["password"],
                                                                                   config["host"],
                                                                                   config["port"],
                                                                                   config["db"]))

    updater = Updater(config["token"])
    updater.dispatcher.add_handler(CommandHandler("start", start))
    updater.dispatcher.add_handler(CallbackQueryHandler(button))
    updater.dispatcher.add_handler(RegexHandler("\/\d+", regex))
    updater.dispatcher.add_handler(MessageHandler(Filters.text & Filters.reply, group_search))
    updater.dispatcher.add_error_handler(error)
    updater.start_polling()
    updater.idle()
