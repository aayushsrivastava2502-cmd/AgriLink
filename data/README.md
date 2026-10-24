# data/

Put real mandi price CSV files here (they are git-ignored). The app ships with **no** real dataset,
so the price estimator starts in clearly labelled demonstration mode.

Expected columns (AGMARKNET / data.gov.in "Current Daily Price of Various Commodities from Various
Markets (Mandis)" format; names are matched loosely, case and punctuation ignored):

    State, District, Market, Commodity, Variety, Grade, Arrival_Date, Min_Price, Max_Price, Modal_Price

Prices in these files are in **Rs per quintal**; the importer divides by 100 to store Rs per kg
(Rs 2,500/quintal = Rs 25/kg). Import with:

    flask --app app import-mandi data\your_file.csv --source "AGMARKNET 2025"

`python -m ml.make_sample_dataset` writes `SYNTHETIC_sample_mandi.csv`: random, seasonal-looking
numbers for testing the pipeline. It is NOT market data and the app labels anything trained on it as synthetic.
