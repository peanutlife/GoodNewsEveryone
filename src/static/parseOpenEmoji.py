import os
import csv

STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'static')
CSV_PATH = os.path.join(STATIC_DIR, 'openmoji.csv')

TOPICS = ["science", "technology", "travel", "health", "culture", "environment", "sports", "kids", "teens", "good news"]

topic_icon_map = {}

with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        annotation = row['annotation'].lower()
        hexcode = row['hexcode']

        for topic in TOPICS:
            if topic in annotation and topic not in topic_icon_map:
                topic_icon_map[topic] = hexcode

print(topic_icon_map)
