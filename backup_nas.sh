#!/bin/bash

# Configurazione
BACKUP_DIR="/mnt/nas_backup"
CONTAINER_NAME="performanceatlete-db-1"
DB_USER="admin"
DB_NAME="atleti_db"
DATE=$(date +%Y-%m-%d_%H%M%S)
FILENAME="backup_atleti_$DATE.sql.gz"

# 1. Verifica che la NAS sia montata prima di iniziare
if mountpoint -q "$BACKUP_DIR"; then
    echo "NAS montata correttamente. Avvio del backup..."
else
    echo "ERRORE: La NAS non è montata in $BACKUP_DIR! Backup annullato."
    exit 1
fi

# 2. Esegui il dump, comprimilo e salvalo sulla NAS
docker exec -t $CONTAINER_NAME pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/$FILENAME

# 3. Pulizia: tiene solo i backup degli ultimi 30 giorni sulla NAS
find $BACKUP_DIR -type f -name "backup_atleti_*.sql.gz" -mtime +30 -delete

echo "Backup completato con successo: $FILENAME"
