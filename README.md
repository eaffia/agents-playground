# agents-playground

Experiments with Docker-based agents running on a VPS.

## agent2
A simple web-check agent that:
- Fetches a URL every 60 seconds
- Logs the HTTP status
- Logs the first line of the page

Run:
cd agent2
docker compose up -d
docker compose logs -f --tail=50

Stop:
docker compose down
