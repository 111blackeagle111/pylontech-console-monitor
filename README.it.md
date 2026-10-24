# Pylontech console monitor

[![CI](https://github.com/111blackeagle111/pylontech-console-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/111blackeagle111/pylontech-console-monitor/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/111blackeagle111/pylontech-console-monitor)](https://github.com/111blackeagle111/pylontech-console-monitor/releases)

Italiano | [English](README.md)

Una piccola dashboard web da installare in casa per i banchi di batterie Pylontech (US2000C, US3000C e simili), letti dalla **porta console** RS232 del modulo master. È un solo script Python, di solito in un container Docker su un Raspberry Pi, e non richiede Home Assistant, un broker MQTT o altro hardware oltre al cavo console.

È nata per rispondere a una domanda pratica: *uno dei miei moduli si sta guastando, e quale cella?* Oltre ai soliti valori di carica e potenza, legge lo stato di salute di ogni cella, i contatori di protezione e il registro eventi che il BMS conserva al suo interno.

![Dashboard](docs/dashboard.png)

## Funzioni

- **Riepilogo del banco:** potenza, carica media, energia utilizzabile sopra la soglia di passaggio alla rete dell'inverter, autonomia stimata o tempo per la carica completa.
- **Vista del rack:** ogni modulo su una riga, dall'alto in basso, con carica, tensione, corrente, temperatura delle celle e tensione di tutte le 15 celle, colorate in base allo scostamento dalla mediana del modulo.
- **Salute delle celle:** le celle segnalate come anomale dal BMS (`soh N`) sono evidenziate.
- **Dettagli del modulo** (pulsante *Dettagli*): cicli, capacità nominale e residua, Ah scaricati in totale, stato e codici di guasto del BMS, temperature della scheda e dei MOSFET, sfasamento dell'orologio del BMS, numero di serie e firmware, tutti i contatori di protezione (sovratensione, sovracorrente, cortocircuito, temperatura, spegnimenti, eventi di salute...) con la variazione degli ultimi 7 giorni.
- **Registro eventi** del modulo master.
- **Avvisi** per celle anomale, stati del BMS, moduli lontani dalla media del banco e celle molto sbilanciate.
- **Grafici** (6 ore, 24 ore, 7 e 30 giorni): carica per modulo, scarto fra le celle per modulo, potenza del banco.
- **Tema chiaro e scuro**, funziona anche sul telefono.
- I dati sono salvati in file CSV mensili; ogni giorno viene salvata una copia dei contatori di protezione, per accorgersi di un modulo che peggiora.

![Dettaglio modulo](docs/module-detail.png)

## Solo lettura

Lo script invia alla console solo comandi di lettura:

| Comando | A cosa serve | Frequenza |
|---|---|---|
| `pwr` | riepilogo di tutti i moduli (carica, tensione, corrente, temperature, stati, orologio del BMS) | ogni ciclo (30 s) |
| `bat N` | tensione, temperatura e bilanciamento di ogni cella | ogni ciclo |
| `soh N` | stato di salute di ogni cella | ogni 10 cicli |
| `pwr N`, `stat N` | stato, codici di guasto, capacità, cicli e contatori di protezione | ogni 20 cicli |
| `info N` | numero di serie, firmware, scheda | ogni 120 cicli |
| `log` | registro eventi del master (solo le prime pagine) | ogni 20 cicli |

Non invia mai comandi di configurazione, ora, spegnimento, reset, login o aggiornamento.

## Hardware

- Un **cavo console** Pylontech (da RJ45 a USB o RS232), lo stesso usato con il programma Pylontech BatteryView. Il lato RJ45 va nella porta **CONSOLE** del modulo **master**, quello collegato all'inverter.
- Un qualsiasi computer Linux con Python 3 o Docker. Provato su un Raspberry Pi 4 con Debian 12.

La porta console può essere usata da un solo programma alla volta: ferma il monitor prima di usare BatteryView.

Se la console non risponde (per esempio dopo un'interruzione di corrente), lo script invia la sequenza standard di risveglio a 1200 baud e poi passa a 115200 baud.

## Installazione con Docker

```bash
git clone https://github.com/111blackeagle111/pylontech-console-monitor.git
cd pylontech-console-monitor
cp .env.example .env
```

Modifica `.env`:

- `PYLON_DEVICE`: il dispositivo seriale del cavo. Meglio il percorso stabile che vedi con `ls -l /dev/serial/by-id/`.
- `DIALOUT_GID`: il GID del gruppo `dialout` dell'host (`getent group dialout`), così il container apre la porta senza girare come root.
- `NOMINAL_AH`: capacità di un modulo (50 per US2000C, 74 per US3000C).
- `CUTOFF_SOC`: la carica alla quale il tuo inverter torna sulla rete; serve per stimare energia utilizzabile e autonomia.

Poi avvialo con l'immagine già pronta (amd64, arm64, armv7):

```bash
docker compose pull
docker compose up -d
```

oppure costruiscila in locale:

```bash
docker compose up -d --build
```

Apri `http://<host>:8765`.

## Test

```bash
pip install pyserial
python3 -m unittest discover -s tests -v
```

I test usano output reali della console di un banco di 4 × US2000C (senza numeri di serie) e una porta seriale finta, quindi non serve nessuna batteria.

## Avvio senza Docker

```bash
pip install pyserial
PYLON_PORT=/dev/ttyUSB0 HOST=0.0.0.0 python3 pylon_monitor.py
```

## Configurazione

| Variabile | Predefinito | Significato |
|---|---|---|
| `PYLON_PORT` | `/dev/ttyUSB0` | porta seriale (nel container è `/dev/ttyPylon`) |
| `PYLON_DATA` | cartella dello script | cartella dei file CSV (volume `/data` in Docker) |
| `HOST` | `127.0.0.1` | indirizzo di ascolto (`0.0.0.0` in Docker) |
| `PORT` | `8765` | porta web |
| `INTERVAL` | `30` | secondi fra due letture |
| `NOMINAL_AH` | `50` | capacità di un modulo in Ah |
| `CUTOFF_SOC` | `30` | soglia di passaggio alla rete dell'inverter, % |

## API

| Indirizzo | Contenuto |
|---|---|
| `GET /api/latest` | ultima lettura di tutti i moduli, dettagli, registro eventi |
| `GET /api/history?hours=24` | storico ridotto (carica, scarto celle, potenza) |
| `GET /api/stats?days=30` | copie giornaliere dei contatori di protezione |

## Dati

- `pylontech-AAAA-MM.csv`: una riga per modulo a ogni lettura.
- `pylontech-stat-AAAA-MM.csv`: contatori di protezione, una volta al giorno.

Circa 0,8 MB al giorno per un banco di 4 moduli.

## Sicurezza

Non c'è autenticazione. Tienilo nella rete di casa o dietro una VPN (Tailscale, WireGuard) e non esporre la porta su internet.

## Note

- L'interfaccia è in italiano.
- I nomi dei contatori arrivano dal BMS (`stat N`); le etichette in italiano sono una traduzione ragionata e passando il mouse si vede il codice originale.
- Il registro eventi è solo quello del master: la console non ha un comando per il registro dei singoli moduli.
- L'orologio del BMS è spesso sbagliato; la dashboard mostra di quanto.
- Le stime di autonomia ed energia assumono moduli di uguale capacità e usano la carica media.

## Avvertenze

Progetto non affiliato a Pylontech. Uso a proprio rischio: lo script legge soltanto, ma la responsabilità dell'impianto resta tua.

## Licenza

[MIT](LICENSE)
