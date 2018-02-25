#!/bin/env python3

"""Converts old PostgreSQL Dortos 'pythonbot' table to four new tables"""

import json
import locale
import os
import urllib.parse
import urllib.request
from datetime import date, datetime

import psycopg2
import psycopg2.extras

import postgresql

insert_institute_sql = "INSERT INTO institute VALUES(%s,%s,date%s,date%s);"
update_institute_sql = "UPDATE institute SET name=%s,date_start=date%s,date_end=date%s WHERE id=%s;"

insert_group_sql = 'INSERT INTO "group" VALUES(%s,%s,%s);'

insert_user_sql = 'INSERT INTO "user" VALUES(%s,%s,%s,%s,%s,%s,%s);'
update_user_sql = 'UPDATE "user" SET login=%s,first_name=%s,last_name=%s,group_id=%s,role=%s,update_time=%s WHERE guid=%s;'

insert_fullchat_sql = 'INSERT INTO chat VALUES(%s,%s,%s,%s);'
insert_chat_sql = 'INSERT INTO chat(id,week,group_id) VALUES(%s,%s,%s);'
insert_nogroupchat_sql = 'INSERT INTO chat(id,week) VALUES(%s,%s);'
update_fullchat_sql = 'UPDATE chat SET week=date%s,guid=%s,group_id=%s WHERE id=%s;'
update_chat_sql = 'UPDATE chat SET week=date%s,group_id=%s WHERE id=%s;'
update_nogroupchat_sql = 'UPDATE chat SET week=date%s WHERE id=%s;'

def get_request(url: str) -> str:
    return urllib.request.urlopen(url).read().decode()

def check_group(group_id: int) -> None:
    cursor.execute('SELECT COUNT(id) FROM "group" WHERE id=%d' % (int(group_id)))
    result = cursor.fetchall()[0][0]
    if (result == 0):
        group = json.loads(get_request("https://api.dortos.ru/v2/groups/getById?id_group=%d" % (group_id)))[0]
        cursor.execute(insert_group_sql, (int(group['ID']), int(group['id_inst']), group['name_group']))

"""Return new dictionary with login and password for PostgreSQL"""
def get_authinfo() -> dict:
    path = os.path.expanduser("~/.config/dortosbot/config.json")
    with open(path) as f:
        config_str = f.read()
    config = json.loads(config_str)
    return {
        "login": config["login"],
        "password": config["password"]
    }

if __name__ == "__main__":
    global db
    authinfo = get_authinfo()

    db = postgresql.open("pq://%s:%s@localhost:5432/dortos?client_encoding=utf-8" % (authinfo["login"], authinfo["password"]))
    db.prepare("INSERT INTO institute VALUES ($1::integer,$2::varchar,$3::date,$4::date)")(3,
                                                                                           'Ты пидор!',
                                                                                           date(2018,1,7),
                                                                                           date(2018,5,26))
    db.close()

    db = psycopg2.connect("dbname='dortos' user='%s' host='localhost' password='%s'" % (authinfo["login"], authinfo["password"]))
    db.set_client_encoding('UTF8')

    locale.resetlocale()
    print("Filling/updating institutes")
    institutes = json.loads(get_request("https://api.dortos.ru/v2/institute/get"))
    for institute in institutes:
        print("Inserting %s" % (institute))
        date_start = datetime.strptime(institute["date_start"], "%Y-%m-%d").date()
        date_end = datetime.strptime(institute["date_end"], "%Y-%m-%d").date()
        query_str = "INSERT INTO institute VALUES({},'{}',date'{}',date'{}');".format(int(institute["ID"]),
                                                                                      institute["name"],
                                                                                      institute["date_start"],
                                                                                      institute["date_end"])
        cursor = db.cursor()
        try:
            cursor.execute(insert_institute_sql, (int(institute["ID"]), institute["name"], institute["date_start"], institute["date_end"]))
        except psycopg2.IntegrityError:
            db.rollback()
            cursor.execute(update_institute_sql, (institute["name"], institute["date_start"], institute["date_end"], int(institute["ID"])))
        db.commit()
        cursor.close()
    print("Institutes filled successfully", end="\n\n")
    print("Fetching chats from table pythonbot")
    cursor = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute("SELECT * FROM pythonbot;")
    rows = cursor.fetchall()
    
    for row in rows:
        cursor = db.cursor()
        print("chat_id={}, date={}, login={}, group_id={}".format(row['chatid'], row['selectedweek'], row['dortosguid'], row['groupid']))
        user_group = None
        if (row['dortosguid'] != None):
            user = json.loads(get_request("https://api.dortos.ru/v2/user/auth?login=%s" % (row["dortosguid"])))[0]
            check_group(user['id_group'])
            try:
                cursor.execute(insert_user_sql, (user["GUID"], 
                                                 user["ID"], 
                                                 user["first_name"], 
                                                 user["last_name"], 
                                                 user["id_group"], 
                                                 user["id_role"], 
                                                 date.today()))
            except psycopg2.IntegrityError:
                db.rollback()
                cursor.execute(update_user_sql, (user["ID"], 
                                                 user["first_name"], 
                                                 user["last_name"], 
                                                 user["id_group"], 
                                                 user["id_role"], 
                                                 date.today(), 
                                                 user["GUID"]))
            try:
                cursor.execute(insert_fullchat_sql, (row["chatid"], row["selectedweek"], user["GUID"], row["groupid"]))
            except psycopg2.IntegrityError:
                db.rollback()
                cursor.execute(update_fullchat_sql, (row["selectedweek"], user["GUID"], row["groupid"], row["chatid"]))
        elif (row['groupid'] != None):
            check_group(row['groupid'])
            try:
                cursor.execute(insert_chat_sql, (row["chatid"], row["selectedweek"], row["groupid"]))
            except psycopg2.IntegrityError:
                db.rollback()
                cursor.execute(update_chat_sql, (row["selectedweek"], row["groupid"], row["chatid"]))
        else:
            try:
                cursor.execute(insert_nogroupchat_sql, (row["chatid"], row["selectedweek"]))
            except psycopg2.IntegrityError:
                db.rollback()
                cursor.execute(update_nogroupchat_sql, (row["selectedweek"], row["chatid"]))
        db.commit()
        cursor.close()
    db.close()
