#!/usr/bin/python

# Nextcloud Trashbin Cleaner.
# Copyright (c) 2024 Tom Laermans.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

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

def delete_item(base_url, href, username, password):
    """
    Deletes an item from the trash bin using its WebDAV href.
    """
    delete_url = f"{base_url}{href}"
    response = requests.request("DELETE", delete_url, auth=(username, password))

    return (response.status_code == 204, response.status_code, response.text)

def purge_files(base_url, username, password, patterns, min_age, threshold, dry_run, force, verbose, progress):
    """
    Deletes files from the trash bin matching any of the specified patterns.

    Args:
        matching_items (list): List of items to process.
        base_url (str): Base URL for the WebDAV server.
        username (str): Username for authentication.
        password (str): Password for authentication.
        patterns (list): Regex patterns for filename matching.
        min_age (int): Minimum age in days of the file.
        threshold (int): Only delete files if less than this amount of matching files is found (unless forced).
        dry_run (bool): If True, don't actually delete files.
        force (bool): Delete files regardless of how many were found (ignore threshold)
        verbose (int): Verbosity level.
        progress (bool): If True, display a progress bar.
    """
    if verbose:
        print("Listing trashbin contents...")

    # Construct the trashbin URL
    trashbin_url = construct_trashbin_url(base_url, username)
    if verbose >= 2:
        print(f"Constructed trashbin URL: {trashbin_url}")

    items = list_trashbin(trashbin_url, username, password)
    if not items:
        print("Trashbin is empty or failed to retrieve contents.")
        return

    if verbose:
        print(f"Found {len(items)} items in the trashbin.")

    # Combine all patterns into a single regex
    combined_pattern = "|".join(f"({pattern})" for pattern in patterns)

    # Filter items based on patterns
    matching_items = []
    for item in items:
        if re.match(combined_pattern, item["filename"]):
            if item['age_in_days'] is not None and item["age_in_days"] >= min_age:
                if verbose >= 3:
                    print(f"{item['getlastmodified']} is older than {min_age} ({item['age_in_days']} days)")
                matching_items.append(item)

    if verbose:
        print(f"{len(matching_items)} items match the patterns {patterns} with minimum age of {min_age} days.")
    if not force and len(matching_items) > threshold:
        print(f"Threshold of {threshold} exceeded. Aborting operation.")
        print("Files that would be deleted:")
        for item in matching_items:
            href = unquote(item["href"])
            filename = href.split("/")[-1]
            print(f"- {filename}")
        return

    # Set up tqdm progress bar if requested (can't combine with dry run)
    if progress and not dry_run:
        # Only import tqdm when actually needed, so it does not become a hard dependency
        # Error out if it cannot be loaded, with a hopefully helpful hint
        try:
            from tqdm import tqdm
        except:
            print("ERROR: Progress bar requires 'tqdm' python module.\n\nTry installing it:\n  - apt install python3-tqdm (Debian, Ubuntu)\n  - dnf install python3-tqdm (Fedora, Red Hat)\n  - zypper install python3-tqdm (SUSE)\n  - pip install tqdm");
            return

        matching_items = tqdm(matching_items, desc="Processing items", unit="file", ascii=' █', dynamic_ncols=True)

        # Disable verbose when requesting progress bar, below prints would interfere with output
        verbose = 0

    if verbose:
        print(f"Deleting {len(matching_items)} matching items.")
    for item in matching_items:
        href = unquote(item["href"])
        if not dry_run:
            if verbose >= 2:
                print(f"Deleting {item['filename']}...")

            # If progress bar was requested, update the bar to show the current file name being deleted.
            if progress:
                matching_items.set_description(f"{item['filename'][:40]:40}")

            (success, status_code, response_text) = delete_item(base_url, href, username, password)
            if success:
                if verbose:
                    print(f"Deleted: {href}")
            else:
                print(f"Failed to delete {href}: {status_code}, {response_text}")
        else:
            print(f"Dry run - not deleting {item['filename']}")

def main():
    global args

    parser = argparse.ArgumentParser(description="Purge files matching patterns from Nextcloud trash bin.")
    parser.add_argument("files", metavar="files", nargs="+", help="One or more INI configuration files to process in order.")
    parser.add_argument("-D", "--dry-run", action="store_true", help="Perform a dry run without deleting files (disables progress bar).")
    parser.add_argument("-F", "--force", action="store_true", help="Force deletion even when amount of files is over threshold.")
    parser.add_argument("-v", "--verbose", action="count", help="Enable verbose output.", default=0)
    parser.add_argument("-C", "--progress", action="store_true", help="Show progress bar (disables verbose output).")

    args = parser.parse_args()

    for config_file in args.files:
        if args.verbose:
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

            # Print configuration summary
            if args.verbose:
                print("Purging files matching:")
                print(f" - File name patterns: {patterns}")
                if not args.force:
                    print(f" - Maximum threshold of {threshold} files")
                print(f" - Minimum age of {min_age} days")

            # Purge the files matching the requirements
            purge_files(base_url, username, password, patterns, min_age, threshold, args.dry_run, args.force, args.verbose, args.progress)

        except Exception as e:
            print(f"Error processing {config_file}: {e}")

if __name__ == "__main__":
    main()
