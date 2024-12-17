import openai
import os
from binance.client import Client
from binance.exceptions import BinanceAPIException
from datetime import datetime, timedelta
import time
import requests
import re
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configure logging to write to a file and the console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trades.log"),  # Log to a file named "trades.log"
        logging.StreamHandler()            # Also log to the console
    ]
)


# Binance client initialization (using testnet)
binance_client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET"),
)
# binance_client.API_URL = 'https://testnet.binance.vision/api'  # Use testnet URL


# Load environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")

# Instantiate the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

symbols = ["BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "AVAX", "LINK", "SHIB", "XLM", "XTZ"]
# symbols = ["BTC", "ETH", "BNB", "XRP", "ADA"]


PROMPT_FOR_AI = f"""
You are an advanced trading AI designed to maximize profits while minimizing risks in cryptocurrency trading. Your mission is to achieve the highest possible return over one month, trading the following cryptocurrencies: BTC, ETH, XRP, SOL, DOGE, ADA, AVAX, LINK, SHIB, XLM, and XTZ. You have access to real-time market data, technical indicators, and news.

Key Rules and Considerations

Risk Management:

Never risk more than 15% of the total account balance on any single trade.
Maintain a cash reserve of at least 20% of the total balance to capitalize on sudden opportunities.
Use stop-losses to limit losses on any trade to 3% of the total account balance.

Trading Strategies:

Use technical analysis (MACD, Bollinger Bands, Moving Averages, RSI, Stochastic Oscillators, Fibonacci Retracements) to identify trends and entry/exit points.
Incorporate news sentiment analysis to identify opportunities driven by breaking events or developments.
Trade only when there is a high-confidence setup based on a combination of technical and fundamental indicators.

Market Conditions:

Adapt strategies based on market trends (bullish, bearish, or sideways).

Decision Frequency:

Make decisions every 30 minutes based on updated data.
Avoid overtrading; do not execute more than 5 trades per hour unless there is an exceptionally strong rationale.

Execution Options:

buy_crypto_price(symbol, amount): Buy cryptocurrency for a specified dollar amount.
buy_crypto_limit(symbol, amount, limit): Set a limit order to buy at a specific price.
sell_crypto_price(symbol, amount): Sell cryptocurrency for a specified dollar amount.
sell_crypto_limit(symbol, amount, limit): Set a limit order to sell at a specific price.
cancel_order(orderId): Cancel an open order.
do_nothing(): Use when there are no clear opportunities.

Critical:

Base every decision on data provided (crypto info, balance, positions, historical data, news, open orders).
Your response should only consist of ONE line and in this EXACT format: command("symbol", amount, [optional limit]). Example: buy_crypto_price("BTC", 30).

Provided Data:

Crypto Info (symbol, ask_price, bid_price, high_price, low_price, volume)
Balance
Open Orders (id, type, side, quantity, price)
Positions (symbol, quantity, average_buy_price, cost_basis, portfolio_percentage)
Historical Data (10-minute interval for the past week: open, close, high, low, volume)
News Headlines (top 3 for each cryptocurrency, include sentiment analysis if possible)

The current date and time is {datetime.now().isoformat()}.

Your Objective: Make intelligent, data-driven decisions to maximize returns while protecting the account from excessive risk. Always prioritize profits and avoid overtrading.
"""
past_trades = []

def record_trade(action, symbol, amount, limit=None):
    trade_info = {
        "action": action,
        "symbol": symbol,
        "amount": amount,
        "time": datetime.now().isoformat(),
        "portfolio_value_usd": get_portfolio_value_in_usd(),

    }
    if limit is not None:
        trade_info["limit"] = limit
    past_trades.append(trade_info)
    if len(past_trades) > 10:  # Keep only the last 10 trades
        past_trades.pop(0)

def get_crypto_infos():
    infos = {}
    for symbol in symbols:
        ticker = binance_client.get_ticker(symbol=f"{symbol}USDT")
        infos[symbol] = {
            'symbol': symbol,
            'ask_price': float(ticker['askPrice']),
            'bid_price': float(ticker['bidPrice']),
            'high_price': float(ticker['highPrice']),
            'low_price': float(ticker['lowPrice']),
            'volume': float(ticker['volume']),
        }
    return infos

def get_balance():
    account_info = binance_client.get_account()
    for asset in account_info['balances']:
        if asset['asset'] == 'USDT':
            return float(asset['free'])  # Use USDT as the base currency
    return 0

def buy_crypto_price(symbol, amount):
    order = binance_client.order_market_buy(
        symbol=f"{symbol}USDT",
        quoteOrderQty=amount  # Specify the amount in USD
    )
    record_trade("buy_crypto_price", symbol, amount)
    logging.info(f"Buy market order placed: {order}")

def buy_crypto_limit(symbol, amount, limit):
    quantity = round(amount / limit, 6)
    order = binance_client.order_limit_buy(
        symbol=f"{symbol}USDT",
        quantity=quantity,
        price=limit
    )
    record_trade("buy_crypto_limit", symbol, amount, limit)
    logging.info(f"Buy limit order placed: {order}")

def sell_crypto_price(symbol, amount):
    order = binance_client.order_market_sell(
        symbol=f"{symbol}USDT",
        quoteOrderQty=amount  # Specify the amount in USD
    )
    record_trade("sell_crypto_price", symbol, amount)
    logging.info(f"Sell market order placed: {order}")

def sell_crypto_limit(symbol, amount, limit):
    quantity = round(amount / limit, 6)
    order = binance_client.order_limit_sell(
        symbol=f"{symbol}USDT",
        quantity=quantity,
        price=limit
    )
    record_trade("sell_crypto_limit", symbol, amount, limit)
    logging.info(f"Sell limit order placed: {order}")

def get_open_orders():
    open_orders = binance_client.get_open_orders()
    return [
        {
            'id': order['orderId'],
            'symbol': order['symbol'],
            'side': order['side'],
            'price': float(order['price']),
            'quantity': float(order['origQty']),
        }
        for order in open_orders
    ]

def get_positions():
    account_info = binance_client.get_account()
    positions = []
    for asset in account_info['balances']:
        quantity = float(asset['free'])
        if quantity > 0 and asset['asset'] in symbols:  # Only include symbols the bot trades
            try:
                ticker = binance_client.get_ticker(symbol=f"{asset['asset']}USDT")
                current_price = float(ticker['lastPrice'])
                total_value = round(quantity * current_price, 2)
                positions.append({
                    'symbol': asset['asset'],
                    'quantity': round(quantity, 4),  # Limit decimals for clarity
                    'current_price': round(current_price, 2),
                    'total_value_usdt': total_value
                })
            except BinanceAPIException as e:
                logging.warning(f"Could not fetch data for {asset['asset']}USDT: {e}")
    return positions

def get_portfolio_value_in_usd():
    # Fetch current positions
    positions = get_positions()
    # Calculate total value of all positions in USD
    portfolio_value = sum(pos['total_value_usdt'] for pos in positions)
    # Add the USDT balance
    portfolio_value += get_balance()
    return round(portfolio_value, 2)


def cancel_order(orderId):
    binance_client.cancel_order(orderId=orderId)
    logging.info(f"Order cancelled: {orderId}")

def get_historical_data():
    historicals = {}
    for symbol in symbols:
        klines = binance_client.get_klines(
            symbol=f"{symbol}USDT",
            interval=Client.KLINE_INTERVAL_10MINUTE,
            limit=100
        )
        historicals[symbol] = [
            {
                'begins_at': kline[0],  # Open time
                'open_price': float(kline[1]),
                'close_price': float(kline[4]),
                'high_price': float(kline[2]),
                'low_price': float(kline[3]),
                'volume': float(kline[5]),
            }
            for kline in klines
        ]
    return historicals

def get_all_crypto_news():
    API_KEY = os.getenv("NEWSAPI_KEY")
    all_news = {}

    for symbol in symbols:
        url = f'https://newsapi.org/v2/everything?q={symbol}&apiKey={API_KEY}'
        response = requests.get(url)
        data = response.json()
        
        news_data = []
        try:
            for article in data['articles'][:3]:  # Limit to top 3 articles
                news_data.append({
                    'title': article['title'],
                    'source': article['source']['name'],
                })
            all_news[symbol] = news_data
        except:
            return all_news

    return all_news

def get_trade_advice():
    crypto_info = get_crypto_infos()
    balance = get_balance()
    positions = get_positions()
    news = get_all_crypto_news()
    open_orders = get_open_orders()
    past_trade_info = '\n'.join([str(trade) for trade in past_trades])

    # Combine data into the prompt
    info_str = f"Crypto Info: {crypto_info}\nBalance: {balance}\nPositions: {positions}\nNews: {news}\nOpen Orders: {open_orders}\nPast Trades: {past_trade_info}"
    prompt = PROMPT_FOR_AI + "\n\n" + info_str

    user_prompt = """
What should we do to make the most amount of profit based on the info?

buy_crypto_price(symbol, amount) This will buy the specified dollars of the specified cryptocurrency.
buy_crypto_limit(symbol, amount, limit) This will set a limit order to buy the specified dollars of the specified cryptocurrency if it reaches the specified limit.
sell_crypto_price(symbol, amount) This will sell the specified dollars of the specified cryptocurrency.
sell_crypto_limit(symbol, amount, limit) This will set a limit order to sell the specified dollars of the specified cryptocurrency if it reaches the specified limit.
cancel_order(orderId) This will cancel the specified order.
do_nothing() Use this when you don't see any necessary changes.

CRITICAL: RESPOND IN ONLY THE ABOVE FORMAT. EXAMPLE: buy_crypto_price("BTC", 30). ONLY RESPOND WITH ONE COMMAND.
    """

    # Log or print the prompt
    print(f"Prompt sent to OpenAI:\n{prompt}\n\nUser prompt:\n{user_prompt}")

    # Call the OpenAI API
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
    )
    print('response from openai:', response.choices[0].message.content)
    return response.choices[0].message.content


def execute_response(response):
    try:
        match = re.match(r'(\w+)\((.*?)\)', response)
        if match:
            command = match.group(1)
            args = [arg.strip().strip('\"') for arg in match.group(2).split(',')]
            command_map = {
                "buy_crypto_price": buy_crypto_price,
                "buy_crypto_limit": buy_crypto_limit,
                "sell_crypto_price": sell_crypto_price,
                "sell_crypto_limit": sell_crypto_limit,
                "cancel_order": cancel_order,
                "do_nothing": lambda *args: None
            }
            function_to_execute = command_map.get(command)
            if function_to_execute:
                logging.info(f"Executing command: {command} with args: {args}")
                function_to_execute(*args)
                portfolio_value = get_portfolio_value_in_usd()
                logging.info(f"Portfolio value in USD: {portfolio_value}")
            else:
                logging.error(f"Invalid command received: {command}")
        else:
            logging.error(f"Invalid response format: {response}")
    except BinanceAPIException as e:
        logging.error(f"Binance API Exception: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

while True:
    execute_response(get_trade_advice())
    time.sleep(1800)  # Run every 15 minutes
