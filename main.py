import streamlit as st
from sqlalchemy import text
from pyxirr import xirr
import pandas as pd

STOCK_OPTIONS = ["00692", "006208", "0050", "2330"]
PROJECTION_RATE = {"worst": 0.065, "average": 0.09, "best": 0.115}

# connect to SQLite db
conn = st.connection("sqlite_db", type="sql", url="sqlite:///investment.db")


# SQL Schema
# CREATE TABLE log(
#         id INTEGER PRIMARY KEY,
#         stock_code TEXT NOT NULL,
#         time TEXT NOT NULL,
#         amount NUMERIC NOT NULL);


st.title("IRR Calculator/投資報酬率計算機")
st.header("Log Cash Flow/現金流紀錄")
stock = st.selectbox("Stock code/股票代碼", STOCK_OPTIONS, key="submit")  # str
time = st.date_input("Date/日期")  # date object
amount = st.number_input(
    "Amount/金額", step=10000, value=-10000, format="%d"
)  # integer
st.markdown("⚠️ Note: Enter **NEGATIVE** value for investment.")
st.markdown("⚠️ 注意：若為投資金額，請輸入**負數**")

if st.button("Save/儲存"):
    with conn.session as s:
        query = text("INSERT INTO log (stock_code, time, amount) VALUES (:s, :t, :a)")
        params = {"s": stock, "t": time, "a": amount}
        s.execute(query, params=params)
        s.commit()
    st.success("Saved successfully!/儲存成功!")

st.header("Calculate IRR/計算報酬率")
stock = st.selectbox("Stock code/股票代碼", STOCK_OPTIONS, key="get")  # str
current_value = st.number_input(
    "Current market value/現在市場價值", min_value=0, value=None, format="%d"
)  # integer
today = (
    pd.Timestamp.now().normalize()
)  # datetime object to conform to pd.to_datetime later

if st.button("Begin calculation/開始計算"):
    query = "SELECT time, amount FROM log WHERE stock_code = :s"
    df = conn.query(query, params={"s": stock}, ttl=0)
    if not current_value or not stock:
        st.warning("Fill in the boxes first!請先填資料!")
    elif df.empty:
        st.warning("No data in the database yet./資料庫中無資料")
    else:
        data = pd.DataFrame(df)
        data["time"] = pd.to_datetime(data["time"])
        data.loc[len(data)] = [today, current_value]
        try:
            # Use xirr for unperiodic IRR calculation
            annual_irr = xirr(data["time"], data["amount"])
            st.metric("Annual IRR/年報酬率", f"{annual_irr:.2%}")

            # Convert to monthly IRR
            monthly_irr = (1 + annual_irr) ** (1 / 12) - 1
            st.metric("Monthly IRR/月報酬率", f"{monthly_irr:.2%}")

            book_profit = current_value + df["amount"].sum()
            st.metric("Book profit/帳面盈虧", f"${book_profit:,}")

            projection = pd.DataFrame({"Year": [i for i in range(31)]})
            projection["worst_case"] = current_value * (
                (1 + PROJECTION_RATE["worst"]) ** projection["Year"]
            )
            projection["average_case"] = current_value * (
                (1 + PROJECTION_RATE["average"]) ** projection["Year"]
            )
            projection["best_case"] = current_value * (
                (1 + PROJECTION_RATE["best"]) ** projection["Year"]
            )
            projection = round(projection)
            st.markdown("**30-year projection/30年預測**    (6.5% vs 9% vs 11.5%)")
            st.line_chart(
                projection,
                y=["worst_case", "average_case", "best_case"],
                x_label="Year/年",
                y_label="Total amount/總額",
            )

        except TypeError:
            st.warning("Error: Cannot calculate./錯誤：無法計算")

if st.button("History/歷史紀錄"):
    df = conn.query(
        "SELECT stock_code AS Stock, time AS Date, amount AS Amount FROM log ORDER BY Date DESC;",
        ttl=0,
    )
    st.dataframe(df)
