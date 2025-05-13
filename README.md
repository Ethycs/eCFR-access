
This project took me 2hrs to complete with only one hand due to a surgery

# eCFR Metrics

A Python application that analyzes the Electronic Code of Federal Regulations (eCFR) to extract and visualize metrics about regulatory text by agency.

## Overview

This project downloads XML data from the official eCFR API, processes it to extract metrics like word count and checksums for each agency's regulations, and provides both an API and a web interface to explore these metrics.

## Features

- **Automatic Title Discovery**: Queries the eCFR API to discover which titles are available
- **Robust Data Fetching**: 
  - Implements rate limiting with concurrency capped to 5 requests
  - Uses exponential backoff for 429 (Too Many Requests) responses
  - Falls back up to 5 days if current date's data isn't available
  - Skips titles that consistently return 404 errors
- **Metrics Calculation**:
  - Word count per agency
  - Checksum generation for data integrity verification
- **API Server**: FastAPI-based server providing endpoints for accessing the metrics
- **Web Dashboard**: Streamlit-based UI for visualizing the metrics with charts and tables

## Project Structure

```
eCFR/
├── data/                  # Directory for storing downloaded data
│   └── snapshot.json      # Generated metrics in JSON format
├── src/
│   └── ecfr/
│       ├── __init__.py    # Package initialization
│       ├── ingest_api.py  # Downloads and processes eCFR data
│       ├── metrics.py     # Metrics calculation utilities
│       ├── api.py         # FastAPI server implementation
│       └── ui.py          # Streamlit UI implementation
├── pyproject.toml         # Project configuration and dependencies
└── README.md              # This file
```

## Installation

This project uses [pixi](https://github.com/prefix-dev/pixi) for dependency management.

1. Install pixi if you don't have it already
2. Clone this repository
3. Run `pixi install` in the project directory

## Usage

The project provides several commands through pixi:

### Data Ingestion

```bash
pixi run ingest
```

This will:
1. Query the eCFR API to discover available titles
2. Download XML data for each title
3. Process the data to extract metrics
4. Save the metrics to `data/snapshot.json`

You can also specify specific titles to download:

```bash
pixi run ingest -- 1 5 12 50
```

### API Server

```bash
pixi run api
```

This starts a FastAPI server at http://localhost:8000 with the following endpoints:

- `/agencies` - Returns a list of all agencies
- `/metrics` - Returns metrics for all agencies
- `/checksum/{agency}` - Returns the checksum for a specific agency

### Web UI

```bash
pixi run ui
```

This starts a Streamlit web interface at http://localhost:8501 that displays:

- A sortable table of agency metrics
- A bar chart of word counts by agency
- A line chart of the Regulatory Volatility Index (RVI) if available

### Run Everything

```bash
pixi run all
```
* currently bugged, need to run ui separately with this option
This runs all three components in sequence: ingest, api, and ui.

## API Endpoints

- **GET /agencies**: Returns a list of all agencies in the dataset
- **GET /metrics**: Returns detailed metrics for all agencies
- **GET /checksum/{agency}**: Returns the checksum for a specific agency

## Technical Details

### Data Flow

1. The `ingest_api.py` script downloads XML data from the eCFR API
2. It processes this data to extract metrics and saves them to `data/snapshot.json`
3. The `api.py` server reads this JSON file and serves the data through its endpoints
4. The `ui.py` Streamlit app fetches data from the API server and visualizes it

### Rate Limiting

The eCFR API has a guideline of 60 requests per minute. To respect this limit, the application:

- Caps concurrency to 5 simultaneous requests
- Implements exponential backoff when receiving 429 responses
- Adds jitter to retry delays to prevent request synchronization

### Error Handling

- If a title returns a 404 error, it's skipped after the maximum number of retries
- If no data is available for the current date, the application tries up to 5 days back
- XML validation is performed to ensure the data is properly formatted

## Known Issues

- The API server depends on a `today_metrics()` function that may not be properly implemented
- The metrics.py file may contain duplicate or conflicting code

## License

This project is licensed under the terms specified in the LICENSE file.
