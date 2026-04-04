# PWA Icons

Questa directory contiene le icone per la Progressive Web App (PWA) di GufoBox.

## File presenti

| File | Dimensioni | Utilizzo |
|------|-----------|----------|
| `icon-192x192.png` | 192×192 px | Icona standard PWA (Android, Chrome) |
| `icon-512x512.png` | 512×512 px | Icona alta risoluzione PWA (splash screen) |
| `apple-touch-icon.png` | 180×180 px | Icona per iOS (Safari "Aggiungi a schermata Home") |
| `favicon.svg` | 64×64 px | Favicon vettoriale (browser moderni) |

## Note

I file PNG presenti sono **placeholder** con colore brand `#4a90d9` (blu GufoBox).
Per la produzione, sostituirli con icone reali che includano il logo GufoBox (il gufo 🦉).

### Requisiti per le icone di produzione

- **Formato**: PNG con sfondo opaco (non trasparente) per le icone `maskable`
- **Colore di sfondo consigliato**: `#4a90d9` (blu GufoBox) oppure `#ffffff`
- **Safe zone maskable**: il logo deve stare nel cerchio centrale (80% del totale)
- Strumento consigliato: [PWA Asset Generator](https://github.com/elegantapp/pwa-asset-generator)

### Genera icone da favicon.svg

```bash
npx pwa-asset-generator frontend/public/icons/favicon.svg frontend/public/icons \
  --background "#4a90d9"
```
