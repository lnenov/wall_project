# Wall Construction Simulation API (Single-Threaded, Database Version)

This Django project simulates the construction of the Night's Watch wall based on an input profile of initial heights and calculates resource usage (ice) and cost. This version uses a **single-threaded simulation** logic where all active crews work simultaneously each day.

It stores wall profiles, section states, and daily results in a database (SQLite by default) and exposes a REST API to query the results.

## Features

*   Reads wall profiles from a configuration file.
*   **Persists** wall profiles, section states, and daily results to the database.
*   Clears previous simulation data before loading new data via the management command.
*   Simulates day-by-day construction using **single-threaded logic** or **multi-process logic**:
    *   All incomplete sections (< 30 ft) increase height by 1 foot each day.
    *   Calculates daily ice usage (195 cubic yards/foot).
    *   Calculates cumulative construction cost (1900 Gold Dragons/cubic yard).
*   Stores simulation results (daily ice/cost) in the database.
*   Exposes REST API endpoints using Django REST Framework, querying the database.

## Setup

1.  **Clone the repository or use this generated structure.**

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows:
    # venv\Scripts\activate
    # On macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Prepare Input File:** Ensure you have an `input.txt` file in the project root directory with the wall profiles (space-separated initial heights, one profile per line). Example:
    ```
    21 25 28
    17
    17 22 17 19 17
    ```

5.  **Run Django migrations (Essential for DB setup):**
    ```bash
    python manage.py migrate
    ```

## Running the Simulation

Before using the API, you **must** run the simulation using the management command. This clears old data, loads the `input.txt` data into the database, calculates all the daily results sequentially, and stores them back in the database.

# Single threaded logic

```bash
python manage.py run_simulation <path_to_input_file>
```

**Example:**

```bash
python manage.py run_simulation input.txt
```

*   Replace `input.txt` with the actual path to your configuration file.
*   The `--number_of_teams` argument is **not** used in this version.

# Multi process logic

```bash
python manage.py run_simulation <path_to_input_file> --number_of_teams <n_teams>
```

**Example:**

```bash
python manage.py run_simulation input.txt --number_of_teams 4
```

*   Replace `input.txt` with the actual path to your configuration file.

## Running the Development Server

Once the simulation has been run successfully and data is in the database, start the Django development server:

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/api/`.

## API Endpoints

*   **GET `/api/profiles/<profile_id>/days/<day_number>/`**
    *   Gets the amount of ice (cubic yards) used *on* a specific `day_number` for the given `profile_id`.
    *   Example: `http://127.0.0.1:8000/api/profiles/1/days/2/`
    *   Returns: `{"day": 2, "ice_amount": 585}` (Value depends on input)

*   **GET `/api/profiles/<profile_id>/overview/<day_number>/`**
    *   Gets the cumulative construction cost *up to and including* `day_number` for the specified `profile_id`.
    *   Example: `http://127.0.0.1:8000/api/profiles/3/overview/5/`
    *   Returns: `{"day": 5, "cost": 1852500}` (Value depends on input)

*   **GET `/api/profiles/overview/<day_number>/`**
    *   Gets the *overall* cumulative construction cost across *all profiles* up to and including `day_number`.
    *   Example: `http://127.0.0.1:8000/api/profiles/overview/10/`
    *   Returns: `{"day": 10, "cost": 15000000}` (Value depends on input)

*   **GET `/api/profiles/overview/`**
    *   Gets the *final total* construction cost across *all profiles* after the entire simulation is complete (retrieved from stored metadata or latest record).
    *   Example: `http://127.0.0.1:8000/api/profiles/overview/`
    *   Returns: `{"day": null, "cost": 32233500}` (Value depends on input)

**Notes:**

*   Profile IDs (`profile_id`) are 1-based (corresponding to the `original_index` field, based on the line number in `input.txt`).
*   Day numbers (`day_number`) are 1-based.
*   All numeric values in JSON responses are integers.
*   Data persistence relies on the database (SQLite default).

## Next steps

* Ask a bot for help with tests for multi process simulation

* Ask a bot to try to reduce the "if-elsy" feeling in the views. Fail and do it myself?

* Update multi process to make sure the original process waits for each team to do their daily work.
  Attempts so far ended up in almost predictable deadlocks :(
