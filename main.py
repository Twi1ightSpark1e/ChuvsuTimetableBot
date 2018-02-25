#!/bin/env python3

# Launch command: TELEBOT_BOT_TOKEN="317427611:AAFXYT8tSw3WCtWjw7uhB63pErctoEFycaw" LC_ALL="ru_RU.UTF-8" ./main.py

import copy
import json
import locale
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
#from pprint import pprint

import postgresql
from telegram import (ForceReply, InlineKeyboardButton,
                      InlineKeyboardMarkup, ParseMode)
from telegram.error import TimedOut
from telegram.ext import (CallbackQueryHandler, CommandHandler, Filters,
                          MessageHandler, RegexHandler, Updater)

import kbd
import strings

TELEGRAM_BOT = None
MINIMAL_DATE=date(2018, 2, 5)
MAXIMAL_DATE=date(2018, 5, 21)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

"""Return new dictionary with login and password for PostgreSQL"""
def load_config() -> dict:
    path = os.path.expanduser("~/.config/dortosbot/config.json")
    if not os.path.isfile(path):
        print("Configuration file {} is not found!\n".format(path) +
              "You MUST fill it with 6 values: host,port,login,password,db,token\n" +
              "    host - PostgreSQL destination host\n" +
              "    port - PostgreSQL destination port\n" +
              "   login - PostgreSQL login\n" +
              "password - PostgreSQL password\n" +
              "      db - PostgreSQL database\n" +
              "   token - Telegram Bot Api token")
        exit(1)
    with open(path) as f:
        config_str = f.read()
    return json.loads(config_str)

def start(bot, update):
    current_date = max(date.today(), MINIMAL_DATE)
    if (current_date.weekday() == 6):
        current_date += timedelta(days=1)
    current_date -= timedelta(days=current_date.weekday())
    if (len(update.message.text) != 6):
        argument = update.message.text[7:]
        response = json.loads(get_request("https://api.dortos.ru/v2/user/auth?login={}".format(argument)))
        groupid = int(json.loads(get_request("https://api.dortos.ru/v2/groups/search?q={}&id_inst=2".format(urllib.parse.quote_plus(response[0]["name_group"]))))[0]["ID"])

        if (PGSQLDB.query("SELECT COUNT(chatid) FROM pythonbot WHERE chatid={};".format(update.message.chat.id))[0]["count"] == 0):
            query_str = "INSERT INTO pythonbot (chatid,selectedweek,dortosguid,groupid) VALUES ({},date'{}','{}','{}');".format(update.message.chat.id,
                                                                                                                                current_date,
                                                                                                                                argument,
                                                                                                                                groupid)
        else:
            query_str = "UPDATE pythonbot SET dortosguid='{}',groupid={},selectedweek=date'{}' WHERE chatid={};".format(argument, groupid, current_date, update.message.chat.id)
    else:
        if (PGSQLDB.query("SELECT COUNT(chatid) FROM pythonbot WHERE chatid={};".format(update.message.chat.id))[0]["count"] == 0):
            query_str = "INSERT INTO pythonbot (chatid,selectedweek) VALUES ({},date'{}')".format(update.message.chat.id,
                                                                                                  current_date)
        else:
            query_str = "UPDATE pythonbot SET selectedweek=date'{}' WHERE chatid={};".format(current_date, update.message.chat.id)
    print(query_str)
    PGSQLDB.execute(query_str)
    reply_markup = InlineKeyboardMarkup(kbd.START_KEYBOARD)
    update.message.reply_text("Выберите пункт меню", reply_markup=reply_markup)

def home(bot, query):
    reply_markup = InlineKeyboardMarkup(kbd.START_KEYBOARD)
    bot.edit_message_text(chat_id=query.message.chat_id, 
                          message_id=query.message.message_id, 
                          reply_markup=reply_markup, 
                          text="Выберите пункт меню",
                          parse_mode=ParseMode.MARKDOWN)

def get_request(url: str) -> str:
    return urllib.request.urlopen(url).read().decode()

def timetable_handler(bot, query):
    current_keyboard = copy.deepcopy(kbd.DAYS_KEYBOARD)
    db = PGSQLDB.query("SELECT groupid,selectedweek FROM pythonbot WHERE chatid={};".format(query.message.chat_id))
    minimal_date = max(MINIMAL_DATE, db[0]["selectedweek"])
    current_date = max(date.today(), minimal_date)
    if (current_date.weekday() == 6):
        current_date += timedelta(days=1)
    if ("_" in query.data):
        #current_date = current_date.replace(day=current_date.day-current_date.weekday()+int(query.data[-1:]))
        parameter = query.data[10:]
        if (parameter == "prev"):
            current_date = max(MINIMAL_DATE, minimal_date - timedelta(days=7))
            PGSQLDB.query("UPDATE pythonbot SET selectedweek=date'{}' WHERE chatid={};".format(current_date, query.message.chat_id))
        elif (parameter == "next"):
            current_date = min(MAXIMAL_DATE, minimal_date + timedelta(days=7))
            PGSQLDB.query("UPDATE pythonbot SET selectedweek=date'{}' WHERE chatid={};".format(current_date, query.message.chat_id))
        else:
            current_date -= timedelta(days=current_date.weekday())
            current_date += timedelta(days=int(parameter))
    if (db[0]["groupid"] == None):
        #group is not selected
        search_handler(bot, query)
        return
    else:
        groupid = db[0]["groupid"]
    
    current_weekday = current_date.weekday()
    current_keyboard[0][current_weekday] = InlineKeyboardButton("*{}*".format(kbd.DAYS_KEYBOARD[0][current_weekday].text), 
                                                                callback_data=kbd.DAYS_KEYBOARD[0][current_weekday].callback_data)
    reply_markup = InlineKeyboardMarkup(current_keyboard)
    group_name = json.loads(get_request("https://api.dortos.ru/v2/groups/getById?id_group={}".format(groupid)))[0]["name_group"]
    timetable = json.loads(get_request("https://api.dortos.ru/v2/timetable/get?date_start={0}&date_end={0}&group_id={1}".format(current_date, groupid)))
    reply_text = "👥 *{}*\n📅 *{} {}*\n\n".format(group_name, 
                                                  current_date.day, 
                                                  strings.MONTHS[current_date.month-1])
    for lesson in timetable:
        if ("printed" in lesson and lesson["printed"] != True) or ("printed" not in lesson):
            if (lesson["id_sub_group"] == '0'):
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
    response = PGSQLDB.query("SELECT dortosguid FROM pythonbot WHERE chatid={};".format(query.message.chat_id))
    if (len(response) == 0 or response[0]["dortosguid"] == None):
        #group is not selected
        bot.send_message(text="""Вы не зарегистрировались в боте!
Для регистрации необходимо авторизоваться на сайте https://dortos.ru и нажать на кнопку с иконкой Telegram сверху
Откроется приложение на этом чате с кнопкой Старт внизу
Нажмите её, и регистрация будет завершена!""", chat_id=query.message.chat_id, reply_markup=kbd.HOME_MARKUP)
        return
    id = response[0]["dortosguid"]
    person_info = json.loads(get_request("https://api.dortos.ru/v2/user/auth?login={}".format(id)))
    institutes = json.loads(get_request("https://api.dortos.ru/v2/institute/get"))
    group_name = json.loads(get_request("https://api.dortos.ru/v2/groups/getById?id_group={}".format(person_info[0]["id_group"])))
    reply = """Вы авторизованы как {} {}\n{} {} {}""".format(person_info[0]["first_name"],
                                                             person_info[0]["last_name"],
                                                             strings.ROLES[int(person_info[0]["id_role"])],
                                                             group_name[0]["name_group"],
                                                             [name["name"] for name in institutes if name["ID"] == str(person_info[0]["id_inst"])][0])
    bot.edit_message_text(chat_id=query.message.chat_id, message_id=query.message.message_id, text=reply, reply_markup=kbd.HOME_MARKUP)

def search_handler(bot, query):
    bot.delete_message(chat_id=query.message.chat_id,
                       message_id=query.message.message_id)
    bot.send_message(chat_id=query.message.chat_id, text=strings.SEARCH_STRING, reply_markup=ForceReply(force_reply=True))

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
    PGSQLDB.execute("UPDATE pythonbot SET groupid={} WHERE chatid={};".format(id, chatid))
    print("UPDATE pythonbot SET groupid={} WHERE chatid={};".format(id, chatid))

def regex(bot, update):
    response = json.loads(get_request("https://api.dortos.ru/v2/groups/getById?id_group={}".format(update.message.text[1:])))
    if (len(response) == 0):
        bot.send_message(chat_id=update.message.chat.id, text="Выбранной группы не существует!", reply_markup=kbd.HOME_MARKUP)
    else:
        select_group(int(update.message.text[1:]), update.message.chat.id)
        bot.send_message(chat_id=update.message.chat.id, text="Выбрана группа {}".format(response[0]["name_group"]), reply_markup=kbd.HOME_MARKUP)

def group_search(bot, update):
    if (update.message.reply_to_message.text == strings.SEARCH_STRING):
        search_results = json.loads(get_request("https://api.dortos.ru/v2/groups/search?q={}&id_inst=2".format(urllib.parse.quote_plus(update.message.text))))
        if (len(search_results) == 1):
            select_group(int(search_results[0]["ID"]), update.message.chat.id)
            bot.send_message(chat_id=update.message.chat.id, text="Выбрана группа {}".format(search_results[0]["name_group"]), reply_markup=kbd.HOME_MARKUP)
            return
        if (len(search_results) == 0):
            bot.send_message(chat_id=update.message.chat.id, text="По вашему запросу ничего не найдено", reply_markup=kbd.HOME_MARKUP)
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
        logger.warning('Update "%s" caused error "%s"', update, error)

if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "ru_RU.UTF-8")
    locale.resetlocale()

    global PGSQLDB
    config = load_config()
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
