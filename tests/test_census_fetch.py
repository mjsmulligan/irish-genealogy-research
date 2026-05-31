import requests
import time
import csv
import os
import argparse

def fetch_multi_year_ded_data(api_config, county, ded_name, output_dir="."):
    session = requests.Session()
    summary = {}
    
    for year, config in api_config.items():
        offset = 0
        limit = 1000
        all_records = []
        
        api_url = config['url']
        print(f"Starting extraction for {year}...")
        
        while True:
            params = {
                'county': county,
                'ded__icontains': ded_name,
                'limit': limit,
                'offset': offset
            }
            
            if 'census_year' in config:
                params['census_year'] = config['census_year']
            
            try:
                response = session.get(api_url, params=params)
                response.raise_for_status()
                
                data = response.json()
                records = data.get('results', [])
                
                if not records:
                    break
                    
                all_records.extend(records)
                print(f"  Fetched {len(records)} records for {year} at offset {offset}.")
                
                if len(records) < limit:
                    break
                    
                offset += limit
                time.sleep(1) 
                
            except requests.exceptions.RequestException as e:
                print(f"Request failed for {year}: {e}")
                break

        if all_records:
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, f"{ded_name.lower()}_{year}.csv")
            headers = all_records[0].keys()
            
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(all_records)
                
            print(f"Export complete for {year}. Saved to {output_file}\n")
            summary[year] = len(all_records)
        else:
            print(f"No records found for {year} or API structure mismatch.\n")
            summary[year] = 0

    # Final Summary Output
    print("-" * 40)
    print("EXTRACTION SUMMARY")
    print("-" * 40)
    print(f"County: {county}")
    print(f"DED:    {ded_name}")
    print("-" * 40)
    for year, count in summary.items():
        print(f"{year} Census: {count} records")
    print("-" * 40)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Irish Census data for a specific County and DED.")
    parser.add_argument("-c", "--county", required=True, help="Target county (e.g., Donegal)")
    parser.add_argument("-d", "--ded", required=True, help="Target District Electoral Division (e.g., Tullynaught)")
    parser.add_argument("-o", "--output", default=".", help="Output directory for the CSV files")
    
    args = parser.parse_args()

    api_endpoints = {
        "1901": {
            "url": "https://api-census.nationalarchives.ie/census/query",
            "census_year": "1901"
        },
        "1911": {
            "url": "https://api-census.nationalarchives.ie/census/query",
            "census_year": "1911"
        },
        "1926": {
            "url": "https://c26-api.nationalarchives.ie/api/census/query_c26a"
        }
    }
    
    fetch_multi_year_ded_data(
        api_config=api_endpoints,
        county=args.county,
        ded_name=args.ded,
        output_dir=args.output
    )