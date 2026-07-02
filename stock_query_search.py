import os
import asyncio
from typing import Optional
import dashscope
from qwen_agent.agents import Assistant
from qwen_agent.gui import WebUI
import pandas as pd
from sqlalchemy import create_engine
from qwen_agent.tools.base import BaseTool, register_tool
import matplotlib.pyplot as plt
import io
import base64
import time
import numpy as np

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'SimSun', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

system_prompt = """我是股票查询助手，以下是关于股票历史价格表 stock_price 的字段，我可能会编写对应的SQL，对数据进行查询
-- 股票历史价格表
CREATE TABLE stock_price (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_name TEXT NOT NULL,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    vol REAL,
    amount REAL,
    UNIQUE(ts_code, trade_date)
);
我将回答用户关于股票历史价格的相关问题。
每当 exc_sql 工具返回 markdown 表格和图片时，你必须原样输出工具返回的全部内容（包括图片 markdown），不要只总结表格，也不要省略图片。这样用户才能直接看到表格和图片。
"""

# ====== exc_sql 工具类实现 ======
class ExcSQLTool(BaseTool):
    """
    SQL查询工具，执行传入的SQL语句并返回结果，并自动进行可视化。
    """
    description = '对于生成的SQL，进行SQL查询，并自动可视化'
    parameters = [{
        'name': 'sql_input',
        'type': 'string',
        'description': '生成的SQL语句',
        'required': True
    },
    {
        'name': 'need_visualize',
        'type': 'boolean',
        'description': '是否需要可视化和统计信息，默认True。如果是对比分析等场景可设为False，不进行可视化。',
        'required': False,
        'default': True
    }]

    def call(self, params: str, **kwargs) -> str:
        import json
        import matplotlib.pyplot as plt
        import io, os, time
        import numpy as np
        args = json.loads(params)
        sql_input = args['sql_input']
        db_path = os.path.join(os.path.dirname(__file__), 'stock_data.db')
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        try:
            df = pd.read_sql(sql_input, engine)
            # 前5行+后5行拼接展示
            if len(df) > 10:
                md = pd.concat([df.head(5), df.tail(5)]).to_markdown(index=False)
            else:
                md = df.to_markdown(index=False)
            # 只返回表格
            if len(df) == 1:
                return md
            need_visualize = args.get('need_visualize', True)
            if not need_visualize:
                return md
            desc_md = df.describe().to_markdown()
            # 自动创建目录
            save_dir = os.path.join(os.path.dirname(__file__), 'image_show')
            os.makedirs(save_dir, exist_ok=True)
            filename = f'stock_{int(time.time()*1000)}.png'
            save_path = os.path.join(save_dir, filename)
            # 智能选择可视化方式
            generate_smart_chart_png(df, save_path)
            img_path = os.path.join('image_show', filename)
            img_md = f'![图表]({img_path})'
            return f"{md}\n\n{desc_md}\n\n{img_md}"
        except Exception as e:
            return f"SQL执行或可视化出错: {str(e)}"

def generate_smart_chart_png(df_sql, save_path):
    columns = df_sql.columns
    if len(df_sql) == 0 or len(columns) < 2:
        plt.figure(figsize=(6, 4))
        plt.text(0.5, 0.5, '无可视化数据', ha='center', va='center', fontsize=16)
        plt.axis('off')
        plt.savefig(save_path)
        plt.close()
        return
    x_col = columns[0]
    y_cols = columns[1:]
    x = df_sql[x_col]
    # 如果数据点较多，自动采样10个点
    if len(df_sql) > 20:
        idx = np.linspace(0, len(df_sql) - 1, 10, dtype=int)
        x = x.iloc[idx]
        df_plot = df_sql.iloc[idx]
        chart_type = 'line'
    else:
        df_plot = df_sql
        chart_type = 'bar'
    plt.figure(figsize=(10, 6))
    for y_col in y_cols:
        if chart_type == 'bar':
            plt.bar(df_plot[x_col], df_plot[y_col], label=str(y_col))
        else:
            plt.plot(df_plot[x_col], df_plot[y_col], marker='o', label=str(y_col))
    plt.xlabel(x_col)
    plt.ylabel('数值')
    plt.title('股票数据统计')
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

def init_agent_service():
    """初始化股票助手服务"""
    model_server = os.getenv('MODEL_SERVER_URL', 'https://api.supxh.xin/v1')
    llm_cfg = {
        'model': os.getenv('LLM_MODEL', 'deepseek-v4-pro'),
        'model_type': 'oai',
        'model_server': model_server,
        'api_key': os.getenv('DASHSCOPE_API_KEY', ''),
        'timeout': 30,
        'retry_count': 3,
    }
    # MCP 工具配置
    tools = [{
        "mcpServers": {
            "tavily-mcp": {
                "command": "npx",
                "args": ["-y", "tavily-mcp@0.1.4"],
                "env": {
                    "TAVILY_API_KEY": os.getenv('TAVILY_API_KEY', '')
                },
                "disabled": False,
                "autoApprove": []
            }
        }
    }, 'exc_sql']

    try:
        bot = Assistant(
            llm=llm_cfg,
            name='股票查询助手',
            description='股票历史价格查询与分析',
            system_message=system_prompt,
            function_list=tools,
            files = ['./faq.txt']
        )
        print("助手初始化成功！")
        return bot
    except Exception as e:
        print(f"助手初始化失败: {str(e)}")
        raise

def app_tui():
    try:
        bot = init_agent_service()
        messages = []
        while True:
            try:
                query = input('user question: ')
                file = input('file url (press enter if no file): ').strip()
                if not query:
                    print('user question cannot be empty！')
                    continue
                if not file:
                    messages.append({'role': 'user', 'content': query})
                else:
                    messages.append({'role': 'user', 'content': [{'text': query}, {'file': file}]})
                print("正在处理您的请求...")
                response = []
                for resp in bot.run(messages):
                    print('bot response:', resp)
                messages.extend(response)
            except Exception as e:
                print(f"处理请求时出错: {str(e)}")
                print("请重试或输入新的问题")
    except Exception as e:
        print(f"启动终端模式失败: {str(e)}")

def app_gui():
    try:
        print("正在启动 Web 界面...")
        bot = init_agent_service()
        chatbot_config = {
            'prompt.suggestions': [
                '查询2024年全年贵州茅台的收盘价走势',
                '统计2024年4月国泰君安的日均成交量',
                '对比2024年中芯国际和贵州茅台的涨跌幅',
            ]
        }
        print("Web 界面准备就绪，正在启动服务...")
        WebUI(
            bot,
            chatbot_config=chatbot_config
        ).run()
    except Exception as e:
        print(f"启动 Web 界面失败: {str(e)}")
        print("请检查网络连接和 API Key 配置")

if __name__ == '__main__':
    app_gui()  # 默认启动Web界面 