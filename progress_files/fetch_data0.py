import pandas as pd

def load_prices():
    df = pd.read_csv("isone_mock_data.csv", sep="\t")
    df = df.rename(columns={"Location": "zone", "LmpTotal": "price"}) #renames the columns to simpler things
    df = df.groupby("zone", as_index=False)["price"].mean() #takes the average of the prices, and keeps them as a column
    df["price"] = df["price"].round(2) # rounds to 2 dp
    return df
