# Console cable / Cavo console

[English](#english) | [Italiano](#italiano)

## English

The monitor talks to the RS232 **console port** of the master module at **115200 baud, 8N1**, the same port and speed used by Pylontech BatteryView.

### Cable type

| Battery | Battery-side connector |
|---|---|
| US2000C, US3000C, US5000, UP5000, Force L1/L2 | RJ45 (port labelled **CONSOLE**) |
| US2000 (B/Plus), US3000, UP2500, Phantom-S | RJ11 |

The usual cable is RJ45 (or RJ11) → DB9 → USB serial adapter. Any USB-**RS232** adapter works on Linux; the cable used for testing is a ready-made console cable based on an FTDI FT231X chip.

> **RS232, not TTL.** The console uses RS232 voltage levels (roughly ±5…12 V), not 3.3 V or 5 V logic. Bare USB-UART boards (CP2102, CH340, PL2303 or FTDI modules with TX/RX pins and no level shifter) are TTL: they will not read the console and can be damaged by it. Use a USB-RS232 adapter with a DB9 connector, or put a MAX3232-type level shifter between a TTL board and the battery.

### RJ45 console pinout (US2000C and newer)

| Pin | Signal |
|---|---|
| 3 | RS232 TX (battery transmits) |
| 6 | RS232 RX (battery receives) |
| 8 | RS232 GND |
| 4 | wake-up, +5…12 V |
| 5 | wake-up GND |

Pins 4 and 5 are an optional hardware wake-up input: a pulse of at least 0.5 s at 5–15 mA wakes a sleeping console. Most ready-made cables only use 3, 6 and 8.

**Wiring to a DB9 USB-RS232 adapter** (the adapter is a PC-side DTE port):

| RJ45 pin (battery) | DB9 pin (adapter) | Why |
|---|---|---|
| 3 – battery TX | 2 – RX | the battery's output goes into the adapter's input |
| 6 – battery RX | 3 – TX | the adapter's output goes into the battery's input |
| 8 – GND | 5 – GND | common ground |

TX and RX must cross: battery TX → adapter RX, adapter TX → battery RX. Leave pins 4 and 5 unconnected unless you build the wake-up circuit.

**Connector orientation.** Hold the RJ45 plug with the latch (clip) facing down and the gold contacts facing up and toward you: pin 1 is on the left, pin 8 on the right. This is the standard numbering used by any network cable crimper.

**Quick check with a multimeter.** With the cable plugged into the battery and nothing else connected, measure between pin 3 (battery TX) and pin 8 (GND): an idle RS232 output sits at a negative voltage, typically −5 to −10 V. Seeing it confirms both the pin order and that the port is RS232. About 0 V usually means wrong pins, a sleeping console or a TTL port.

### RJ11 console pinout (older modules)

| Pin | Signal |
|---|---|
| 1 | GND |
| 2 | RXD |
| 3 | TXD |
| 4 | GND |

Swap TX/RX on the adapter side as needed (battery TX → adapter RX).

### If the console does not answer

- Check that the cable is in the **CONSOLE** port of the **master** module (the one linked to the inverter), not in a link or CAN/RS485 port.
- After a power cycle the console can stay silent. The monitor sends the standard 1200 baud wake-up sequence on its own; if that is not enough, unplug and replug the RJ45 connector, or use the hardware wake-up pins described above.
- Only one program at a time can use the port: stop the monitor before using BatteryView.

The pinout above is taken from Pylontech's service procedure for BatteryView. That document is not included in this repository; ask Pylontech or your installer for it.

## Italiano

Il monitor comunica con la **porta console** RS232 del modulo master a **115200 baud, 8N1**, la stessa porta e la stessa velocità usate da Pylontech BatteryView.

### Tipo di cavo

| Batteria | Connettore lato batteria |
|---|---|
| US2000C, US3000C, US5000, UP5000, Force L1/L2 | RJ45 (porta **CONSOLE**) |
| US2000 (B/Plus), US3000, UP2500, Phantom-S | RJ11 |

Il cavo tipico è RJ45 (o RJ11) → DB9 → adattatore seriale USB. Su Linux va bene qualsiasi adattatore USB-**RS232**; per le prove è stato usato un cavo console già pronto con chip FTDI FT231X.

> **RS232, non TTL.** La console lavora con livelli di tensione RS232 (circa ±5…12 V), non con logica a 3,3 V o 5 V. Le schedine USB-UART nude (CP2102, CH340, PL2303 o moduli FTDI con pin TX/RX e senza convertitore di livello) sono TTL: non leggono la console e possono esserne danneggiate. Usa un adattatore USB-RS232 con connettore DB9, oppure metti un convertitore di livello tipo MAX3232 fra la schedina TTL e la batteria.

### Piedinatura RJ45 della console (US2000C e successive)

| Pin | Segnale |
|---|---|
| 3 | RS232 TX (trasmette la batteria) |
| 6 | RS232 RX (riceve la batteria) |
| 8 | RS232 GND |
| 4 | risveglio, +5…12 V |
| 5 | GND del risveglio |

I pin 4 e 5 sono un ingresso di risveglio hardware facoltativo: un impulso di almeno 0,5 s a 5–15 mA risveglia una console addormentata. La maggior parte dei cavi già pronti usa solo i pin 3, 6 e 8.

**Collegamento a un adattatore USB-RS232 con DB9** (l'adattatore è una porta lato PC, DTE):

| Pin RJ45 (batteria) | Pin DB9 (adattatore) | Perché |
|---|---|---|
| 3 – TX della batteria | 2 – RX | l'uscita della batteria entra nell'ingresso dell'adattatore |
| 6 – RX della batteria | 3 – TX | l'uscita dell'adattatore entra nell'ingresso della batteria |
| 8 – GND | 5 – GND | massa comune |

TX e RX vanno incrociati: TX della batteria → RX dell'adattatore, TX dell'adattatore → RX della batteria. Lascia scollegati i pin 4 e 5, a meno di costruire il circuito di risveglio.

**Orientamento del connettore.** Tieni lo spinotto RJ45 con la linguetta (clip) verso il basso e i contatti dorati verso l'alto e verso di te: il pin 1 è a sinistra, il pin 8 a destra. È la stessa numerazione usata da qualsiasi crimpatrice per cavi di rete.

**Controllo rapido col multimetro.** Con il cavo inserito nella batteria e nient'altro collegato, misura fra il pin 3 (TX della batteria) e il pin 8 (GND): un'uscita RS232 a riposo sta a una tensione negativa, di solito fra −5 e −10 V. Se la vedi, l'ordine dei pin è giusto e la porta è RS232. Circa 0 V di solito vuol dire pin sbagliati, console addormentata o porta TTL.

### Piedinatura RJ11 della console (moduli più vecchi)

| Pin | Segnale |
|---|---|
| 1 | GND |
| 2 | RXD |
| 3 | TXD |
| 4 | GND |

Se serve, incrocia TX e RX sul lato adattatore (TX della batteria → RX dell'adattatore).

### Se la console non risponde

- Controlla che il cavo sia nella porta **CONSOLE** del modulo **master** (quello collegato all'inverter), non in una porta link o CAN/RS485.
- Dopo un'interruzione di corrente la console può restare muta. Il monitor invia da solo la sequenza standard di risveglio a 1200 baud; se non basta, stacca e riattacca il connettore RJ45 oppure usa i pin di risveglio hardware descritti sopra.
- La porta può essere usata da un solo programma alla volta: ferma il monitor prima di usare BatteryView.

La piedinatura viene dalla procedura di assistenza Pylontech per BatteryView. Quel documento non è incluso nel repository: chiedilo a Pylontech o al tuo installatore.
