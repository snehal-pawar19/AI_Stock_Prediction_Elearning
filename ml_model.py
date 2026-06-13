import numpy as np

def predict_trend(prices):
    if len(prices) < 5:
        return "Neutral", prices[-1]

    # Simple moving average logic
    short_ma = np.mean(prices[-3:])
    long_ma = np.mean(prices[-5:])

    if short_ma > long_ma:
        trend = "Bullish"
    elif short_ma < long_ma:
        trend = "Bearish"
    else:
        trend = "Neutral"

    predicted_price = round(short_ma + np.random.uniform(-2, 2), 2)

    return trend, predicted_price


def generate_fake_history(current_price):
    prices = []
    price = current_price

    for _ in range(20):
        price += np.random.uniform(-5, 5)
        prices.append(round(price, 2))

    return prices
