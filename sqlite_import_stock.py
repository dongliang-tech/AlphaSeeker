import sqlite3
import pandas as pd
import os

DB_NAME = 'stock_data.db'
SQL_FILE = 'create_stock_price.sql'
EXCEL_FILE = 'stock_history_data.xlsx'

if os.path.exists(DB_NAME):
    os.remove(DB_NAME)
    print(f'已删除旧数据库: {DB_NAME}')

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

with open(SQL_FILE, 'r', encoding='utf-8') as f:
    sql_content = f.read()

cursor.executescript(sql_content)
print('表结构创建成功')

df = pd.read_excel(EXCEL_FILE)
print(f'读取Excel数据: {len(df)} 行')

df.to_sql('stock_price', conn, if_exists='append', index=False)
print('数据导入成功')

cursor.execute('SELECT COUNT(*) FROM stock_price')
count = cursor.fetchone()[0]
print(f'数据库记录数: {count}')

cursor.execute("SELECT * FROM stock_price LIMIT 3")
rows = cursor.fetchall()
print('\n前3条数据:')
for row in rows:
    print(row)

conn.commit()
conn.close()
print(f'\n数据库创建完成: {DB_NAME}')