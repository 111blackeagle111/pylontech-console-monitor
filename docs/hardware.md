# Console cable / Cavo console

[English](#english) | [Italiano](#italiano)

## English

The monitor talks to the RS232 **console port** of the master module at **115200 baud, 8N1**, the same port and speed used by Pylontech BatteryView.

### Cable type

| Battery | Battery-side connector |
|---|---|
| US2000C, US3000C, US5000, UP5000, Force L1/L2 | RJ45 (port labelled **CONSOLE**) |
| US2000 (B/Plus), US3000, UP2500, Phantom-S | RJ11 |

The usual cable is RJ45 (or RJ11) → DB9 → USB serial adapter. Any USB-RS232 adapter works on Linux; an FTDI FT231X was used for testing.

### RJ45 console pinout (US2000C and newer)

| Pin | Signal |
|---|---|
| 3 | RS232 TX (battery transmits) |
| 6 | RS232 RX (battery receives) |
| 8 | RS232 GND |
| 4 | wake-up, +5…12 V |
| 5 | wake-up GND |

Pins 4 and 5 are an optional hardware wake-up input: a pulse of at least 0.5 s at 5–15 mA wakes a sleeping console. Most ready-made cables only use 3, 6 and 8.

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

Il cavo tipico è RJ45 (o RJ11) → DB9 → adattatore seriale USB. Su Linux va bene qualsiasi adattatore USB-RS232; per le prove è stato usato un FTDI FT231X.

### Piedinatura RJ45 della console (US2000C e successive)

| Pin | Segnale |
|---|---|
| 3 | RS232 TX (trasmette la batteria) |
| 6 | RS232 RX (riceve la batteria) |
| 8 | RS232 GND |
| 4 | risveglio, +5…12 V |
| 5 | GND del risveglio |

I pin 4 e 5 sono un ingresso di risveglio hardware facoltativo: un impulso di almeno 0,5 s a 5–15 mA risveglia una console addormentata. La maggior parte dei cavi già pronti usa solo i pin 3, 6 e 8.

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
