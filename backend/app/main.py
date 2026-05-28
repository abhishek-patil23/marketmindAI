from groq import Groq
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from yahooquery import search
import yfinance as yf
import re

# =====================================
# GROQ API
# =====================================
GROQ_API_KEY = "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"
client = Groq(api_key=GROQ_API_KEY)

# =====================================
# FASTAPI
# =====================================
app = FastAPI(title="MarketMind AI")

# =====================================
# CORS
# =====================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================
# IN-MEMORY CACHE & WATCHLIST
# =====================================
analysis_cache = {}
# watchlist stores: { "TSLA": { "ticker": "TSLA", "company": "Tesla, Inc.", "currency": "$" }, ... }
watchlist_store = {}

# =====================================
# INPUT MODELS
# =====================================
class ResearchInput(BaseModel):
    company: str

class AuthInput(BaseModel):
    email: str
    password: str

class WatchlistInput(BaseModel):
    ticker: str
    company: str
    currency: str = "$"

# =====================================
# HOME ROUTE
# =====================================
@app.get("/")
def home():
    return {"message": "MarketMind AI Backend Running"}





# =====================================
# HISTORY ROUTE
# =====================================
@app.get("/history")
def get_history():
    return {
        "history": [
            {"company": v["company"], "ticker": v["ticker"], "key": k}
            for k, v in analysis_cache.items()
        ]
    }

# =====================================
# CACHED RESULT ROUTE
# =====================================
@app.get("/result/{ticker}")
def get_cached_result(ticker: str):
    key = ticker.upper()
    if key in analysis_cache:
        return analysis_cache[key]
    return {"error": "Not found in cache"}

# =====================================
# WATCHLIST ROUTES
# =====================================
@app.get("/watchlist")
def get_watchlist():
    """Return watchlist items with live prices and % change."""
    items = []
    for key, info in watchlist_store.items():
        ticker = info["ticker"]
        currency = info.get("currency", "$")
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            if not hist.empty and len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                previous = hist["Close"].iloc[-2]
                change_pct = ((current - previous) / previous) * 100
                items.append({
                    "ticker": key,
                    "company": info["company"],
                    "price": f"{currency}{round(current, 2)}",
                    "change_pct": round(change_pct, 2),
                    "direction": "up" if change_pct >= 0 else "down",
                })
            elif not hist.empty:
                current = hist["Close"].iloc[-1]
                items.append({
                    "ticker": key,
                    "company": info["company"],
                    "price": f"{currency}{round(current, 2)}",
                    "change_pct": 0.0,
                    "direction": "up",
                })
            else:
                items.append({
                    "ticker": key,
                    "company": info["company"],
                    "price": "N/A",
                    "change_pct": 0.0,
                    "direction": "up",
                })
        except Exception:
            items.append({
                "ticker": key,
                "company": info["company"],
                "price": "N/A",
                "change_pct": 0.0,
                "direction": "up",
            })
    return {"watchlist": items}


@app.post("/watchlist/add")
def add_to_watchlist(data: WatchlistInput):
    """Add a stock to the watchlist."""
    key = data.ticker.upper()
    if key in watchlist_store:
        return {"status": "already_exists", "message": f"{key} is already in your watchlist."}
    watchlist_store[key] = {
        "ticker": data.ticker,
        "company": data.company,
        "currency": data.currency,
    }
    return {"status": "added", "message": f"{key} added to watchlist."}


@app.delete("/watchlist/remove/{ticker}")
def remove_from_watchlist(ticker: str):
    """Remove a stock from the watchlist."""
    key = ticker.upper()
    if key in watchlist_store:
        del watchlist_store[key]
        return {"status": "removed", "message": f"{key} removed from watchlist."}
    return {"status": "not_found", "message": f"{key} not in watchlist."}


@app.get("/watchlist/prices")
def get_watchlist_prices():
    """Lightweight endpoint: return only prices and % change for auto-refresh."""
    items = []
    for key, info in watchlist_store.items():
        ticker = info["ticker"]
        currency = info.get("currency", "$")
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d")
            if not hist.empty and len(hist) >= 2:
                current = hist["Close"].iloc[-1]
                previous = hist["Close"].iloc[-2]
                change_pct = ((current - previous) / previous) * 100
                items.append({
                    "ticker": key,
                    "price": f"{currency}{round(current, 2)}",
                    "change_pct": round(change_pct, 2),
                    "direction": "up" if change_pct >= 0 else "down",
                })
            elif not hist.empty:
                current = hist["Close"].iloc[-1]
                items.append({
                    "ticker": key,
                    "price": f"{currency}{round(current, 2)}",
                    "change_pct": 0.0,
                    "direction": "up",
                })
            else:
                items.append({
                    "ticker": key,
                    "price": "N/A",
                    "change_pct": 0.0,
                    "direction": "up",
                })
        except Exception:
            items.append({
                "ticker": key,
                "price": "N/A",
                "change_pct": 0.0,
                "direction": "up",
            })
    return {"prices": items}

# =====================================
# MARKET CAP FORMAT
# =====================================
def format_market_cap(value):
    try:
        if value >= 1_000_000_000_000:
            return f"${round(value/1_000_000_000_000,2)}T"
        elif value >= 1_000_000_000:
            return f"${round(value/1_000_000_000,2)}B"
        elif value >= 1_000_000:
            return f"${round(value/1_000_000,2)}M"
        return str(value)
    except Exception:
        return "N/A"

# =====================================
# TICKER SEARCH — prefers NSE, then BSE,
# then NASDAQ/NYSE for Indian/US stocks
# =====================================
def resolve_ticker(company_input: str):
    result = search(company_input)
    quotes = result.get("quotes", [])
    if not quotes:
        return None
    # 1st priority: NSE (.NS)
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(".NS"):
            return sym
    # 2nd priority: BSE (.BO)
    for q in quotes:
        sym = q.get("symbol", "")
        if sym.endswith(".BO"):
            return sym
    # 3rd priority: NASDAQ / NYSE
    for q in quotes:
        exchange = str(q.get("exchange", "")).upper()
        sym = q.get("symbol", "")
        if "NASDAQ" in exchange or "NYSE" in exchange:
            return sym
    # Final fallback: first result
    return quotes[0].get("symbol")

# =====================================
# ANALYZE ROUTE
# =====================================
@app.post("/analyze")
def analyze_company(data: ResearchInput):
    try:
        company_input = data.company.strip()
        ticker = resolve_ticker(company_input)
        if not ticker:
            return {"error": "Company not found. Please try a more specific name."}

        # =====================================
        # CHECK CACHE FIRST
        # =====================================
        cache_key = ticker.upper()
        if cache_key in analysis_cache:
            return analysis_cache[cache_key]

        stock = yf.Ticker(ticker)

        # =====================================
        # PRICE DATA
        # =====================================
        hist = stock.history(period="5d")
        current_price = "N/A"
        day_high = "N/A"
        day_low = "N/A"

        # Currency: INR for NSE/BSE, USD for others
        if ticker.endswith(".NS") or ticker.endswith(".BO"):
            currency_symbol = "₹"
        else:
            currency_symbol = "$"

        if not hist.empty:
            current_price = f"{currency_symbol}{round(hist['Close'].iloc[-1], 2)}"
            day_high      = f"{currency_symbol}{round(hist['High'].iloc[-1], 2)}"
            day_low       = f"{currency_symbol}{round(hist['Low'].iloc[-1], 2)}"

        # =====================================
        # COMPANY INFO
        # =====================================
        info = stock.info
        company_name   = info.get("longName", ticker)
        sector         = info.get("sector", "N/A")
        pe_ratio       = info.get("trailingPE", "N/A")
        market_cap     = format_market_cap(info.get("marketCap", 0))
        recommendation = info.get("recommendationKey", "hold").upper()
        target_price   = info.get("targetMeanPrice", "N/A")

        # =====================================
        # ADDITIONAL FINANCIAL METRICS
        # =====================================
        eps_raw = info.get("trailingEps")
        eps = f"{currency_symbol}{round(eps_raw, 2)}" if eps_raw else "N/A"

        rev_growth_raw = info.get("revenueGrowth")
        revenue_growth = f"{round(rev_growth_raw * 100, 1)}%" if rev_growth_raw else "N/A"

        profit_margin_raw = info.get("profitMargins")
        profit_margin = f"{round(profit_margin_raw * 100, 1)}%" if profit_margin_raw else "N/A"

        roe_raw = info.get("returnOnEquity")
        roe = f"{round(roe_raw * 100, 1)}%" if roe_raw else "N/A"

        dte_raw = info.get("debtToEquity")
        debt_to_equity = f"{round(dte_raw, 2)}" if dte_raw else "N/A"

        # =====================================
        # NEWS HEADLINES
        # =====================================
        headlines = []
        try:
            news = stock.news
            for item in news[:5]:
                title = item.get("title")
                if title:
                    headlines.append(title)
        except Exception:
            pass

        if not headlines:
            # Generate realistic news headlines using Groq
            news_prompt = f"""
You are a financial news editor. Based on the data below, write exactly 4 short, specific, realistic news headlines about this company that investors would care about. Each headline must be on its own line. No numbering, no bullet points, no extra text.
Company: {company_name}
Ticker: {ticker}
Sector: {sector}
Current Price: {current_price}
Market Cap: {market_cap}
P/E Ratio: {pe_ratio}
Analyst Recommendation: {recommendation}
Analyst Target Price: {target_price}
Write 4 headlines only. Each must sound like a real financial news headline. Make them specific to this company and sector.
"""
            news_response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You write realistic, specific financial news headlines. Output only the headlines, one per line, nothing else."
                    },
                    {
                        "role": "user",
                        "content": news_prompt
                    }
                ],
                temperature=0.6,
                max_tokens=200
            )
            raw = news_response.choices[0].message.content.strip()
            headlines = [
                line.strip().lstrip("-•*0123456789. ")
                for line in raw.split("\n")
                if line.strip()
            ][:4]

        # =====================================
        # AI PROMPT
        # =====================================
        prompt = f"""
You are a senior equity research analyst at Morgan Stanley.
Write a complete, professional equity research report.
You MUST write ALL sections. Do NOT stop early or truncate.
Company: {company_name}
Ticker: {ticker}
Current Price: {current_price}
Day High: {day_high}
Day Low: {day_low}
Analyst Recommendation: {recommendation}
Analyst Target Price: {target_price}
P/E Ratio: {pe_ratio}
Market Cap: {market_cap}
Sector: {sector}
Recent Headlines:
{headlines}
Write the report using EXACTLY this structure. All 6 key factors are mandatory:
KEY FACTORS
1. [Factor Title]
[2 sentence explanation of why this matters to investors.]
2. [Factor Title]
[2 sentence explanation.]
3. [Factor Title]
[2 sentence explanation.]
4. [Factor Title]
[2 sentence explanation.]
5. [Factor Title]
[2 sentence explanation.]
6. [Factor Title]
[2 sentence explanation.]
RISKS
1. [Risk in 1-2 sentences.]
2. [Risk in 1-2 sentences.]
3. [Risk in 1-2 sentences.]
4. [Risk in 1-2 sentences.]
WHAT INVESTORS SHOULD DO
Verdict: [Buy / Hold / Avoid]
Short-Term Outlook:
[4 sentences about near-term price action and catalysts.]
Long-Term Payoff:
[4 sentences about long-term investment thesis and growth potential.]
Give your prediction what you expect about the stock in one or 2 lines and why and keep one line distance between you and long-term payoff
STRICT RULES:
- NO markdown, NO asterisks, NO hashtags, NO bullet dashes
- Institutional prose only
- MUST complete all 6 key factors and all sections
"""
        # =====================================
        # GROQ RESPONSE
        # =====================================
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional equity research analyst. "
                        "Always write complete reports with all sections. "
                        "Never truncate. Always include all 6 key factors, risks, and investor conclusion."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=3000
        )
        analysis = response.choices[0].message.content
        analysis = analysis.replace("*", "").replace("#", "")

        # =====================================
        # SENTIMENT & CONFIDENCE SCORE (AI)
        # =====================================
        sentiment_prompt = f"""
Based on the following equity research data, provide a market sentiment breakdown and confidence score.
Company: {company_name}
Ticker: {ticker}
Current Price: {current_price}
P/E Ratio: {pe_ratio}
Market Cap: {market_cap}
Analyst Recommendation: {recommendation}
Target Price: {target_price}
EPS: {eps}
Revenue Growth: {revenue_growth}
Profit Margin: {profit_margin}
ROE: {roe}
Debt to Equity: {debt_to_equity}
Reply in EXACTLY this format with numbers only, nothing else:
BULLISH: [number between 0 and 100]
BEARISH: [number between 0 and 100]
NEUTRAL: [number between 0 and 100]
CONFIDENCE: [number between 1.0 and 10.0]
The three sentiment percentages must sum to 100.
"""
        sentiment_response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a quantitative market analyst. Output only the requested numbers in the exact format specified. No extra text."
                },
                {
                    "role": "user",
                    "content": sentiment_prompt
                }
            ],
            temperature=0.2,
            max_tokens=100
        )
        raw_sentiment = sentiment_response.choices[0].message.content.strip()

        # Parse sentiment values
        bullish = 0
        bearish = 0
        neutral = 0
        confidence = 7.0

        for line in raw_sentiment.split("\n"):
            line_upper = line.strip().upper()
            if line_upper.startswith("BULLISH"):
                match = re.search(r'[\d.]+', line)
                if match:
                    bullish = float(match.group())
            elif line_upper.startswith("BEARISH"):
                match = re.search(r'[\d.]+', line)
                if match:
                    bearish = float(match.group())
            elif line_upper.startswith("NEUTRAL"):
                match = re.search(r'[\d.]+', line)
                if match:
                    neutral = float(match.group())
            elif line_upper.startswith("CONFIDENCE"):
                match = re.search(r'[\d.]+', line)
                if match:
                    confidence = min(10.0, max(1.0, float(match.group())))

        # Normalize to 100 if needed
        total = bullish + bearish + neutral
        if total > 0 and total != 100:
            bullish = round(bullish / total * 100, 1)
            bearish = round(bearish / total * 100, 1)
            neutral = round(100 - bullish - bearish, 1)
        confidence = round(confidence, 1)

        # =====================================
        # BUILD & CACHE RESULT
        # =====================================
        result = {
            "company":        company_name,
            "ticker":         ticker,
            "price":          current_price,
            "day_high":       day_high,
            "day_low":        day_low,
            "target_price":   target_price,
            "recommendation": recommendation,
            "market_cap":     market_cap,
            "pe_ratio":       pe_ratio,
            "sector":         sector,
            "headlines":      headlines,
            "analysis":       analysis,
            "eps":            eps,
            "revenue_growth": revenue_growth,
            "profit_margin":  profit_margin,
            "roe":            roe,
            "debt_to_equity": debt_to_equity,
            "bullish":        bullish,
            "bearish":        bearish,
            "neutral":        neutral,
            "confidence":     confidence,
            "currency":       currency_symbol,
        }
        analysis_cache[cache_key] = result
        return result

    except Exception as e:
        return {"error": str(e)}