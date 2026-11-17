# GTA VI Twitch CCU Forecast

![make.fun bounty](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)
![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/shinichibi/gta6-twitch-ccu-forecast-01/rank.svg)
![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/shinichibi/gta6-twitch-ccu-forecast-01/reward.svg)

Entry for the make.fun bounty [gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast, hour by hour, how many people watch Grand Theft Auto VI live on
Twitch over the 24 UTC hours of its release day, 2026-11-19, as five
quantiles per hour for hours 2–24, given everything recorded up to the end of
hour 1.

## How it works

`main.py` (Python 3, standard library only) reads each case file in the
input directory and writes one forecast file per case. It builds the
forecast from the comparable past launches bundled into every case:

1. Each comparable contributes its release-day curve of log-ratios to its
   own first hour.
2. Comparables are weighted by curated tier (clean vs early-access vs
   weak), unlock pattern (rolling midnight-local vs simultaneous global),
   console-only vs PC-including, and first-hour scale similarity to the
   case at hand.
3. Each hour's five quantiles are the weighted quantiles of those
   log-ratios, with the band around the median slightly tightened, applied
   to the case's hour-1 print.

With no usable comparables it falls back to holding hour 1's level with a
slowly widening band, so it always emits a valid forecast. The program is
deterministic: two runs on the same case produce identical bytes.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## License

MIT — see `LICENSE`.
