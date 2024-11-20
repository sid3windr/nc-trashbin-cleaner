#!/usr/bin/python

import argparse
import configparser
import re
import requests
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from datetime import datetime, timezone

def read_config(config_file):
    """
    Reads the INI configuration file.
    """
    config = configparser.ConfigParser()
    config.read(config_file)
    if "Nextcloud" not in config:
        raise ValueError("Missing 'Nextcloud' section in the configuration file.")
    if "patterns" not in config:
        raise ValueError("Missing 'patterns' section in the configuration file.")
    return config

def construct_trashbin_url(base_url, username):
    """
    Constructs the full WebDAV trash bin URL using the base URL and username.
    """
    return f"{base_url}/remote.php/dav/trashbin/{username}/trash"

def list_trashbin(trashbin_url, username, password):
    """
    Fetches the list of items in the Nextcloud trash bin using WebDAV.
    Returns a list of dictionaries with file details including synthesized filename.
    """
    response = requests.request("PROPFIND", trashbin_url, auth=(username, password), headers={"Depth": "1"})
    if response.status_code != 207:
        print(f"Failed to list trashbin: {response.status_code}, {response.text}")
        return []

    # Parse XML response
    tree = ET.fromstring(response.content)
    namespaces = {'d': 'DAV:'}
    items = []

    for response in tree.findall('d:response', namespaces):
        # Extract href
        href = response.find('d:href', namespaces).text
        if not href:
            continue

        # Derive filename from href
        filename = unquote(href.split("/")[-1])

        # Extract properties
        properties = {}
        for prop in response.findall('.//d:prop', namespaces):
            for child in prop:
                tag_name = child.tag.split("}")[-1]  # Strip namespace
                properties[tag_name] = child.text

        # Add href and filename to properties
        properties['href'] = href
        properties['filename'] = filename

        # Parse the getlastmodified date to calculate the age in days
        if 'getlastmodified' in properties and properties['getlastmodified']:
            try:
                # Parse the last modified timestamp
                last_modified = datetime.strptime(
                    properties['getlastmodified'], "%a, %d %b %Y %H:%M:%S %Z"
                ).replace(tzinfo=timezone.utc)

                # Calculate age in days
                current_time = datetime.now(timezone.utc)
                age_in_days = (current_time - last_modified).days
                properties['age_in_days'] = age_in_days
            except ValueError:
                print(f"Could not parse getlastmodified: {properties['getlastmodified']}")
                properties['age_in_days'] = None
        else:
            properties['age_in_days'] = None
            
        items.append(properties)

    return items

def delete_item(trashbin_url, href, username, password):
    """
    Deletes an item from the trash bin using its WebDAV href.
    """
    delete_url = f"{trashbin_url}{href}"
    response = requests.request("DELETE", delete_url, auth=(username, password))
    if response.status_code in (204, 404):
        print(f"Deleted: {href}")
    else:
        print(f"Failed to delete {href}: {response.status_code}, {response.text}")

def purge_files(trashbin_url, username, password, patterns, min_age, threshold):
    """
    Lists and optionally purges files from the trash bin matching any of the specified patterns.
    """
    print("Listing trashbin contents...")
    items = list_trashbin(trashbin_url, username, password)
    if not items:
        print("Trashbin is empty or failed to retrieve contents.")
        return

    print(f"Found {len(items)} items in the trashbin.")

    # Combine all patterns into a single regex
    combined_pattern = "|".join(f"({pattern})" for pattern in patterns)

    # Filter items based on patterns
    matching_items = []
    for item in items:
        if re.match(combined_pattern, item["filename"]):
            if item['age_in_days'] is not None and item["age_in_days"] >= min_age:
                #print(f"{item['getlastmodified']} is older than {min_age} ({item['age_in_days']} days)")
                matching_items.append(item)

    print(f"{len(matching_items)} items match the patterns {patterns} with minimum age of {min_age}.")
    if len(matching_items) > threshold:
        print(f"Threshold of {threshold} exceeded. Aborting operation.")
        print("Files that would be deleted:")
        for item in matching_items:
            href = unquote(item["href"])
            filename = href.split("/")[-1]
            print(f"- {filename}")
        return

    print(f"Deleting up to {threshold} matching items.")
    for item in matching_items:
        href = unquote(item["href"])
        filename = href.split("/")[-1]
        print(f"Deleting {filename}...")
        # FIXME dry-run
        delete_item(trashbin_url, href, username, password)

def main():
    global args

    parser = argparse.ArgumentParser(description="Purge files matching patterns from Nextcloud trash bin.")
    parser.add_argument("files", metavar="files", nargs="+", help="One or more INI configuration files to process in order.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without deleting files.")
    parser.add_argument("-v", "--verbose", help="Enable verbose output.", action="count", default=0)

    args = parser.parse_args()

    for config_file in args.files:
        print(f"Processing configuration file: {config_file}")
        try:
            config = read_config(config_file)
            nextcloud_config = config["Nextcloud"]
            patterns_config = config["patterns"]

            # Extract nextcloud instance details
            base_url = nextcloud_config.get("url")
            username = nextcloud_config.get("username")
            password = nextcloud_config.get("password")

            # Extract script configuration
            min_age = nextcloud_config.getint("minimum_age", fallback=30)  # Default age is 30 days
            threshold = nextcloud_config.getint("threshold", fallback=10)  # Default threshold is 10 files

            # Extract patterns
            patterns = [patterns_config[key] for key in patterns_config]

            # Error out if no nextcloud url or auth details configured, skip to next INI file
            if not base_url or not username or not password:
                print(f"Invalid configuration in {config_file}. Missing required fields.")
                continue

            # Error out if no matching patterns configured, skip to next INI file
            if not patterns:
                print(f"No patterns specified in {config_file}. Skipping.")
                continue

            # Construct the trashbin URL
            trashbin_url = construct_trashbin_url(base_url, username)
            if args.verbose >= 2:
                print(f"Constructed trashbin URL: {trashbin_url}")

            print(f"Purging files matching patterns: {patterns} with threshold: {threshold}.")
            purge_files(trashbin_url, username, password, patterns, min_age, threshold)

        except Exception as e:
            print(f"Error processing {config_file}: {e}")

if __name__ == "__main__":
    main()
