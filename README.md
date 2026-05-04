# CS32-Final-Project-Flood
Final Project for CS32 course (Tom Flood)

This project will aim to create a visual representation of the electrical grid of a section of MA, identifying pressure points on grid capability using data from ISO New England, and having the ability to hover over grid lines or certain areas and it will display the current price of electricity for that area. Additionally, the display will be able to be toggled to not only display live data, but also all the 

The following libraries need to be installed:
pandas
Folium, which is used to make interactive maps with data
Geopandas, which aids panda with extending data analysis to maps and geometry

You need to install the extension for a live server (I downloaded one by Ritwick Dey)

I also needed to register for access to the ISO-NE database, but my credentials are hard coded into the script for ease of use, so the user can use my credentials rather than having to provide their own.

How to run the code:
1. Input into the terminal: "python3 main.py" in order to get prices (in time these will be live from a server)
2. In order to see the website, open the "isone_map.html" by rightclicking and opening in the live server


Citing sources:
For using folium and cloropleth, I used the following youtube video:
https://www.youtube.com/watch?v=Q0z1cPD_7yE
And then I used claude AI to fill in any gaps on how to add certain features, such as the hover.
I also used claude AI to generate the data in the CSV file, but I aim to be able to draw directly from an API in time.

For the files to make the shape of the states, I sourced from the US Census Bureau Cartographic Boundary Files (2022), 1:20m scale. Available at census.gov/geographies/mapping-files.

For the live data pricing, I used an API key from ISO-NE, and then found the documentation for requestion information from the API from the documentation: https://webservices.iso-ne.com/docs/v1.1/
