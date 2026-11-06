# IN Hostel

IN Hostel is a mobile-first hostel management platform for hostel owners. This repository is arranged as a modular Django monolith with a React Native client.

## Project structure

- `backend/` – Django REST API and business logic
- `mobile/` – React Native + TypeScript app
- `docs/` – design and operational documents
- `.env` – local secret environment settings (not committed)
- `.env.example` – template for required configuration

## Phase 1 foundation

This phase establishes the base stack and verifies that the API and mobile client can communicate securely over HTTPS/HTTP in local development.

## Backend setup

1. Open a terminal in the project root.
2. Install Python dependencies:
   ```bash
   python -m pip install Django djangorestframework mysqlclient python-dotenv
   ```
3. Create the local MySQL database (`in_hostel`) and matching credentials using the values in `.env`.
4. If the MySQL service is not reachable in the current local environment, the app will automatically fall back to SQLite via `USE_SQLITE_FALLBACK=True` so the backend can still start for this Phase 1 validation.
5. Start the API:
   ```bash
   cd backend
   python manage.py migrate
   python manage.py runserver 0.0.0.0:8000
   ```

## Mobile setup

1. Install Node dependencies:
   ```bash
   cd mobile
   npm install
   ```
2. Start Metro:
   ```bash
   npm start
   ```
3. Use the API base URL from `.env` (`API_BASE_URL`) for local connectivity.

## Health check

The backend exposes a health endpoint at:

- `GET /api/v1/health/`

## Security notes

- Never commit `.env`.
- Keep all secrets on the backend server.
- Do not place backend credentials inside the mobile app.
- Privacy Policy and Terms URLs should be publicly accessible and configured through environment variables.
