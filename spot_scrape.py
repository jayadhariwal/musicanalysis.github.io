#standard imports
import time
import random
import logging
import pandas as pd
import re
from pathlib import Path
from datetime import datetime, timedelta

#Selinium imports for automatic chrome browser control 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

#Configures the logging module to print info about the progress/status of the scraper
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

#Stealth settings to make the automatic activity look human. 
#hides "chrome is being controlled" tag, among other things
options = Options()
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument('--disable-blink-features=AutomationControlled')

#finds chrome driver, instantiates
s = Service(ChromeDriverManager().install())

#opens and maximizes chrome window, connects driver
driver = webdriver.Chrome(service=s, options=options)
driver.maximize_window()
logging.info("Browser opened.")

#Start scrape at the last week of 2016. Note that Spotify Charts measures 
#weeks by their end date, and also their weeks end on Thursdays.
start_url = "https://charts.spotify.com/charts/view/regional-global-weekly/2016-12-29"
driver.get(start_url)
logging.info("Navigated to start URL.")

#The only way the scraper could run below detection was if chrome was fully
#quit before running. This meant that we would have to sign into Charts again
#each time we ran the script. It pauses here until you press enter and resume it.
input("SCRIPT PAUSED, log in to Spotify and manually navigate to start date.")
logging.info("Resuming script. Starting scrape...")

#to safely extract text without crashing.
#if element found, get text and strip. else, return empty string
def safe_text(elem):
    return elem.text.strip() if elem is not None else ""

#Final csv file path
home_dir = Path.home()
save_path = home_dir / "spotify_weekly_charts_2016-2024.csv"

#empty list for dict of song data
all_chart_data = []

#Use online week calculator to figure out total number of weeks to scrape.
#We scraped 418, which spans from the last full week of 2016 (ending 2016-12-29)
# to the last full week of 2024 (ending 2024-12-26). 
total_weeks_to_scrape = 418

#----------------------OUTER SCRAPING LOOP------------------------
for i in range(total_weeks_to_scrape):
    logging.info(f"Scraping week {i+1} of {total_weeks_to_scrape}...")
    
    #Finding song rows on the page
    try:
        #finds all table rows that are not header rows, by looking for rows
        # that contain links to tracks. waits up to 15 seconds per row
        row_xpath = "//tr[@data-encore-id='tableRow'][.//a[contains(@href, '/track/')]]"
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, row_xpath))
        )
        song_rows = driver.find_elements(By.XPATH, row_xpath)
    
    #to avoid crashes
    except Exception as e:
        logging.warning(f"No song rows found for this week: {e}")
        song_rows = []

    #Getting date, this ended up failing for every week except the 
    #first, but it was easy enough to tidy the weeks column in colab.
    try:
        date_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "weekly_end_date"))
        )
        current_date = date_element.get_attribute('value').strip()
    except Exception:
        current_date = f"week_index_{i}" #Fallback index label

    #Sanity check, should be 200 for each week
    logging.info(f"Scraping {len(song_rows)} songs for week: {current_date}")

    
    #----------------INNER LOOP FOR DATA----------------
    for row in song_rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td") #gets all table cells in row
            
            #sanity check, if row has less than 6 cells something is wrong
            if len(cells) >= 6: 
                
                #cell 3 has title and artist
                track_info = safe_text(cells[2])
                
                #cell 7 has streams
                streams = safe_text(cells[6])   

                #splits up title and artist if separated by newline
                if '\n' in track_info:
                    title, artist = track_info.split('\n', 1)
                else:
                    title = track_info
                    artist = "Unknown" #fallback

                #removes formatting from streaming data, converts to int
                streams_clean = streams.replace(',', '').strip()
                streams_num = int(streams_clean) if streams_clean.isdigit() else None
                
                #add row's data to main list as dict
                all_chart_data.append({
                    "date_week": current_date,
                    "title": title.strip(),
                    "artist": artist.strip(),
                    "weekly_streams": streams_num
                })
        
        #if row parsing failed
        except Exception as e:
            logging.debug(f"Row parse error: {e}")
            continue
    # -----------------END OF INNER LOOP------------------

    #-----SAVES PARTIAL PROGRESS TO CSV EVERY 10 WEEKS---
    #rewrites the file every time
    if (i + 1) % 10 == 0:
        df_partial = pd.DataFrame(all_chart_data) #list of data --> df
        df_partial['weekly_streams'] = pd.to_numeric(df_partial['weekly_streams'], errors='coerce')
        df_partial.to_csv(save_path, index=False) #saves partial data to csv
        logging.info(f"Saved progress at {len(df_partial)} rows.")
    
    #----NAVIGATES TO NEXT WEEK-----------
    #waits 2-4 seconds to navigate to next week
    sleep_time = random.uniform(2.0, 4.0)
    logging.info(f"Scrape complete for this week, sleeping briefly.")
    time.sleep(sleep_time)

    try:
        current_url = driver.current_url
        
        #regular expressions to find date at the end of the current URL
        match = re.search(r'/(\d{4}-\d{2}-\d{2})$', current_url)
        
        #gets date and adds 7 days with timedelta calculation from datetime
        if match:
            current_date_str = match.group(1)
            current_date_obj = datetime.strptime(current_date_str, "%Y-%m-%d")
            next_date_obj = current_date_obj + timedelta(days=7)
            next_date_str = next_date_obj.strftime("%Y-%m-%d")
            
            #replaces old date with new one
            next_url = re.sub(r'\d{4}-\d{2}-\d{2}$', next_date_str, current_url)
            logging.info(f"Navigating to next week: {next_date_str}")

            #driver navigates to next week, waits 2-3 seconds for the page to load
            driver.get(next_url)
            time.sleep(random.uniform(2.0, 3.0))
        #fallback
        else:
            logging.error("Could not find date in URL. Stopping scrape.")
            break
    except Exception as e:
        logging.error(f"Failed to navigate to next week: {e}")
        break
#---------------END OF OUTER LOOP-----------------------

#quit driver
driver.quit()
logging.info("Browser closed, final data save:")

#final save of csv if data was successfully collected.
if not all_chart_data:
    logging.warning("Error, CSV empty.")
else:
    df = pd.DataFrame(all_chart_data)
    df['weekly_streams'] = pd.to_numeric(df['weekly_streams'], errors='coerce')
    
    df.to_csv(save_path, index=False)
    logging.info(f"Success, saved CSV with {len(df)} rows.")