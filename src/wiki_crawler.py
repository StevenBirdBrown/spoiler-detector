# !/usr/bin/env python3
# This script will crawl wikipedia (with API) and search Google
# to retrieve a movie's plot summary/synopsis according to its
# IMDb ID (in the format of regex r'^tt\d{7}$')
# Note: Due to constant network error when browsing imdb/google,
# I cannot guarantee that this script runs smoothly. So many
# checkpoints is inserted to minimize potential data loss.
import requests
import random
import multiprocessing as mp
import pandas as pd
import csv, json
import logging
import re, time
from bs4 import BeautifulSoup
from lxml import etree
from functools import reduce

logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler('wiki_crawler.log')

console_handler.setLevel(logging.DEBUG)
file_handler.setLevel(logging.ERROR)

console_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
file_format = logging.Formatter('%(asctime)s: %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_format)
file_handler.setFormatter(file_format)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

IMDB_URL = 'https://imdb.com/title/'
IMDB_XPATH = '//*[@id="title-overview-widget"]/div[1]/div[2]/div/div[2]/div[2]/h1'
GOOGLE_SITES = ['https://www.google.com.hk/search?&q=', 'https://www.google.com/search?&q=', \
                'https://www.google.com.sg/search?&q=', 'https://www.google.co.uk/search?&q=', \
                'https://www.google.com.tw/search?&q=', 'https://www.google.com.au/search?&q=']

USER_AGENTS = [{"Accept": "*/*",
               "Accept-Language": "en-US,en;q=0.8",
               "Cache-Control": "max-age=0",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36",
               "Connection": "keep-alive",
               "Referer": "https://www.google.com/"
               },
               {"Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.8",
                "Cache-Control": "max-age=0",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8",
                "Connection": "keep-alive",
                "Referer": "https://www.imdb.com/"
               },
               {"Accept": "*/*",
                "Accept-Language": "zh,zh-CN,en-US,en;q=0.8",
                "Cache-Control": "max-age=0",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36",
                "Connection": "keep-alive",
                "Referer": "https://www.netflix.com/"
               }
               ]

WIKI_URL = 'https://en.wikipedia.org/w/api.php'
WIKI_BROWSE_PARAMS = {
    "action": "parse",
    "page": None,
    "format": "json",
    "prop": "wikitext",
    "section": 1
}
WIKI_SEARCH_PARAMS = {
    "action": "query",
    "format": "json",
    "list": "search",
    "srsearch": None
}

def browse_imdb(id):
    '''
    this function will browse the imdb page for movie with ID `id`,
    and obtain its name and release date
    params:
        id - the IMDb primary key of a specific movie
    return value:
        id - same as input
        name - movie name with its release year, such as "The Fate of The Furious (2017)"
    '''
    imdb_url = IMDB_URL + id
    try:
        imdb_page = requests.get(imdb_url).text
    except Exception as e:
        logger.warning('Exception {} occurs in browse_imdb, will retry once'.format(e))
        time.sleep(1)
        try:
            imdb_page = requests.get(imdb_url).text
        except Exception as e:
            logger.error('Exception {} occurs when retrying browse_imdb, abort movie_id: {}' \
                         .format(e, id))
            return

    tree = etree.HTML(imdb_page)
    node = tree.xpath(IMDB_XPATH)[0]
    name = ''.join(node.itertext()).replace(u'\xa0', u' ').strip()
    print('Finish {}'.format(id))
    return id, name

def batch_browse_imdb(ids):
    '''
    this function will run `browse_imdb` on `ids`, a list of IDs
    params:
        ids - a list of IDs
    return value:
        ids_names - a dict, key is IMDb ID, value movie_name
    '''
    with mp.Pool() as pool:
        results = pool.map(browse_imdb, ids)
    
    ids_names = dict()
    for result in results:
        if result:
            ids_names[result[0]] = result[1]
    
    return ids_names

def search_google(query):
    '''
    this function will google `query`, and find the wikipedia page of this movie
    params:
        query - movie name
    return value:
        wiki page name - the movie's wikipedia page's name
    '''
    google_prefix = random.choice(GOOGLE_SITES)
    google_url = google_prefix + query + ' film'
    header = random.choice(USER_AGENTS)
    
    try:
        page = requests.get(url=google_url, headers=header, timeout=5).text
    except Exception as e:
        logger.error('Exception {} occurs in search'.format(e))
        if google_prefix != GOOGLE_SITES[0]:
            page = requests.get(url=GOOGLE_SITES[0]+query, headers=header, timeout=3) 
        else:
            return None

    soup = BeautifulSoup(page, 'html.parser')
    for link in soup.find_all('a'):
        url = link.get('href')
        if url and 'en.wikipedia.org' in url:
            # return the wikipage name, e.g., Black_Panther_(film)
            return url.split('/')[-1]
    return None

def search_wiki(name):
    '''
    this function will use wikipedia api for searching the movie name + 'film',
    and will assume the first result is the desired page
    '''
    params = WIKI_SEARCH_PARAMS
    params['srsearch'] = name
    session = requests.Session()
    try:
        raw_data = session.get(url=WIKI_URL, params=params, timeout=5).json()
    except Exception as e:
        logger.warning('Exception {} occurs in search_wiki, will retry once'.format(e))
        try:
            raw_data = session.get(url=WIKI_URL, params=params, timeout=5).json()
        except Exception as e:
            logger.error('Exception {} occurs when retrying search_wiki, abort movie_name: {}' \
                            .format(e, name))
            return
            
    return name, raw_data['query']['search'][0]['title']

def batch_search_wiki(names):
    '''
    this function will do search_wiki on names with the help of multiprocessing
    '''
    with mp.Pool() as pool:
        results = pool.map(search_wiki, names)
    names_pages = dict()
    
    for result in results:
        if result:
            names_pages[result[0]] = result[1]
    
    return names_pages

def browse_wiki(page):
    '''
    this function will browse the wikipedia page at `url` and retrieve the 'plot'
    section of this movie
    params:
        url - url to a wikipedia page of a movie
    return value:
        a string, the 'plot' section of this page, hopefully it is the first section
        of every wikipage, as set in `PARAMS`
    '''
    params = WIKI_BROWSE_PARAMS
    params['page'] = page
    session = requests.Session()
    try:
        raw_data = session.get(url=WIKI_URL, params=params, timeout=5).json()
    except Exception as e:
        logger.warning('Exception {} occurs in browse_wiki, will retry once'.format(e))
        try:
            raw_data = session.get(url=WIKI_URL, params=params, timeout=5).json()
        except Exception as e:
            logger.error('Exception {} occurs when retrying browse_wiki, abort page_name: {}' \
                            .format(e, page))
            return
    
    try:
        raw_plot = raw_data['parse']['wikitext']['*']
    except Exception as e:
        logger.error('Exception {}: This is a wrong page {}' \
                     .format(e, page))
        return
            
    return page, plot_extractor(raw_plot, page)

def batch_browse_wiki(pages):
    '''
    this function will do browse_wiki on page_names with the help of
    multiprocessing
    '''
    with mp.Pool() as pool:
        results = pool.map(browse_wiki, pages)
    pages_plots = dict()
    
    for result in results:
        if result and result[1]:
            pages_plots[result[0]] = result[1]

    return pages_plots

def plot_extractor(raw_plot, page=''):
    '''
    this function will extract the raw plot summary returned by `browse_wiki`, and
    remove the redundant/unnecessary punctuations and words
    params:
        raw_plot - plot section of wikipage
    return value:
        string, substitute '[[text_a|text_b]]' in raw_plot with 'text_b'
    '''
    # this section could be named "Plot" or "Synopsis"
    title_pattern = r'==.*?(:?Plot|Synopsis).*?=='
    if not re.match(title_pattern, raw_plot):
        logger.error('This is not an actual raw_plot for {}, skipping...'.format(page))
        logger.warning('First several words: {}'.format(raw_plot[:100]))
        return

    subs = (r'\{\{.+?\}\}', ''), (r'\[\[(.*?\|){0,1}(.*?)\]\]', r'\2'), \
           (r'\n+', ' '), (r'<.*?>', ''), (title_pattern, '')

    plot = reduce(lambda a, sub: re.sub(*sub, a), subs, raw_plot)
    return plot.strip()

if __name__ == '__main__':
    logger.info('Load original json file as pandas dataframe')
    # hard code for now
    df_movies = pd.read_json('../data/imdb/IMDB_movie_details.json', lines=True)
    ids = df_movies['movie_id'].tolist()
    
    logger.info('Batch browse IMDb pages of the movies')
    ids_movies = batch_browse_imdb(ids)

    logger.info('Save ids_movies to offline')
    with open('./ids_movies.json', 'w') as f:
        json.dump(ids_movies, f)

    movies = list(ids_movies.values())
    movies_pages = batch_search_wiki(movies)

    ids_pages = dict()
    for id in ids_movies:
        try:
            ids_pages[id] = movies_pages[ids_movies[id]]
        except Exception as e:
            logger.error('No wikipage found for {} - {}'.format(ids, ids_movies[id]))

    logger.info('Write ids_pages to json file')    
    
    with open('./ids_pages.json', 'r') as f1, open('./ids_movies.json', 'r') as f2:
        ids_pages = json.load(f1)
        ids_movies = json.load(f2)

    logger.info('Batch browse wikipedia pages of the movies')
    pages = list(ids_pages.values())
    pages_plots = batch_browse_wiki(pages)

    ids_plots = dict()
    for id in ids_pages:
        # now ids_pages' values are movie plots
        try:
            ids_plots[id] = pages_plots[ids_pages[id]]
        except Exception as e:
            logger.error('No wiki plot found for {} - {}. Keep field plot_summary as original' \
                         .format(id, ids_movies[id]))

    logger.info('Write ids_plots to json file')
    with open('./ids_plots.json', 'w') as f:
        json.dump(ids_plots, f)

    for row in df_movies.iterrows():
        # modify original plot_summary to the one we get from wikipedia
        try:
            row['plot_summary'] = ids_plots[row['movie_id']]
        except Exception as e:
            logger.warning('No wiki plot for {} - {}. Keep field plot_summary as original' \
                           .format(id, ids_movies[id]))

    logger.info('Finish! save dataframe to ../data/imdb/plot.csv')
    df_movies.to_csv('../data/imdb/plot.csv')
