"""
core/offline_generator.py

Genera contenuti offline di esempio usando Piper TTS.
Produce file WAV nelle sottocartelle di OFFLINE_FALLBACK_DIR.
"""

import os
import threading

from config import OFFLINE_FALLBACK_DIR
from core.utils import log

# =========================================================
# TEMPLATE TESTUALI PER OGNI MODALITÀ
# =========================================================

OFFLINE_TEMPLATES = {
    "spoken_quiz": [
        "Domanda numero uno! Di che colore è il cielo quando è sereno? ... La risposta è: blu!",
        "Domanda numero due! Quante zampe ha un gatto? ... La risposta è: quattro!",
        "Domanda numero tre! Come si chiama il verso del cane? ... Si chiama abbaio! Bau bau!",
        "Domanda numero quattro! In che stagione cadono le foglie? ... In autunno!",
        "Domanda numero cinque! Qual è il pianeta più vicino al sole? ... Mercurio!",
        "Domanda numero sei! Quanti giorni ha una settimana? ... Sette giorni!",
        "Domanda numero sette! Come si chiama il cucciolo del cavallo? ... Si chiama puledro!",
        "Domanda numero otto! Di che colore sono le banane mature? ... Gialle!",
        "Domanda numero nove! Quante lettere ha l'alfabeto italiano? ... Ventuno!",
        "Domanda numero dieci! Come si chiama la stella più vicina alla Terra? ... Il Sole!",
        "Domanda numero undici! Che verso fa la mucca? ... Muuu! Si chiama muggito!",
        "Domanda numero dodici! Quante stagioni ci sono in un anno? ... Quattro: primavera, estate, autunno e inverno!",
        "Domanda numero tredici! Come si chiama il re della foresta? ... Il leone!",
        "Domanda numero quattordici! Quanti colori ha l'arcobaleno? ... Sette colori!",
        "Domanda numero quindici! Dove vivono i pesci? ... Nell'acqua! Nel mare, nei fiumi e nei laghi!",
    ],
    "adventure": [
        "Benvenuto avventuriero! Oggi partiamo per un viaggio nella foresta incantata. Gli alberi sono altissimi e il sentiero è coperto di foglie dorate. Cosa farai? Seguirai il sentiero principale o esplorerai il bosco?",
        "Ti trovi davanti a un ponte di legno sopra un fiume. L'acqua scorre veloce e si sentono strani rumori dalla grotta dall'altra parte. Hai il coraggio di attraversare?",
        "Hai trovato una mappa del tesoro! La X segna un punto vicino alla montagna del drago. Il viaggio è lungo ma la ricompensa sarà grande. Preparati all'avventura!",
        "Una fata ti appare davanti e ti dice: Ho bisogno del tuo aiuto! Il mio giardino magico è stato incantato da un folletto dispettoso. Mi aiuterai a rompere l'incantesimo?",
        "Sei arrivato alla caverna dei cristalli! Le pareti brillano di mille colori. In fondo alla caverna c'è uno scrigno. Cosa conterrà? Avvicinati piano piano per scoprirlo!",
        "Il drago amichevole ti offre un passaggio! Sali sulla sua schiena e volate sopra le nuvole. Da lassù puoi vedere tutta la terra degli gnomi. Che meraviglia!",
        "Il folletto del bosco ti propone un indovinello: Cosa ha le radici ma non si vede, cresce verso l'alto ma non ha gambe? ... Un albero! Bravo, hai risposto giusto!",
        "Ti sei perso nella foresta nebbiosa. Ma niente paura! Segui le lucciole che ti guideranno verso casa. Ogni lucciola brilla come una piccola stella.",
    ],
    "personalized_story": [
        "C'era una volta, in un paese lontano lontano, un piccolo gufo che viveva in cima a un albero altissimo. Ogni sera guardava le stelle e sognava di poter volare fino alla luna. Una notte speciale, una stella cadente gli sussurrò un segreto magico...",
        "In fondo al mare, dove la luce del sole arriva appena, viveva un pesciolino arancione di nome Arancino. Non era come gli altri pesci: lui sapeva cantare! E la sua voce era così bella che persino le balene si fermavano ad ascoltarlo.",
        "Nella fattoria di nonno Pietro, tutti gli animali parlavano. La mucca Margherita raccontava barzellette, il gallo Chicchirichì cantava l'opera, e il maialino Rosetto faceva il giornalista. Un giorno arrivò un visitatore molto speciale...",
        "La principessa Luna non voleva stare nel castello. Lei amava esplorare il bosco, arrampicarsi sugli alberi e fare amicizia con gli scoiattoli. Un giorno trovò una porta nascosta dietro una cascata...",
        "Il piccolo robot Bip viveva in una città del futuro. Sapeva fare tutto: cucinare, pulire, e persino raccontare storie! Ma c'era una cosa che non sapeva fare: ridere. Fino al giorno in cui incontrò una bambina di nome Sofia...",
        "C'era una volta un trenino rosso che si era perso. Non ricordava più la strada per tornare alla stazione. Ma lungo il viaggio incontrò tanti amici: una farfalla, un coniglio e un saggio gufo che gli indicò la via di casa.",
        "Il draghetto Fuoco aveva paura del buio. Ogni sera, quando arrivava la notte, nascondeva la testa sotto le ali e tremava. Ma un giorno la luna gli insegnò che nel buio si nascondono tante cose bellissime: le stelle, le lucciole, e i sogni!",
        "C'era una volta una nuvola dispettosa che non voleva far piovere. I fiori erano assetati, i fiumi si asciugavano. Poi arrivò una bambina che le cantò una ninna nanna così bella che la nuvola si commosse... e finalmente piovve!",
    ],
    "guess_sound": [
        "Ascolta bene questo suono! Miao miao miao! Chi è? ... È un gattino! Bravo!",
        "Senti questo verso: Bau bau bau! Chi sarà? ... È un cagnolino! Esatto!",
        "Ecco un altro suono: Muuuu! Muuuu! Lo riconosci? ... È una mucca! Bravissimo!",
        "Ascolta: Chicchirichì! Chi fa questo verso la mattina presto? ... Il gallo! Giusto!",
        "Che suono è questo? Bzzzzz bzzzzz! ... È un'ape! Fa il miele ma attenzione, punge!",
        "Ascolta bene: Cra cra cra! Chi è questo animaletto verde? ... Una rana! Vive vicino agli stagni!",
        "Ecco un verso speciale: Ih oh ih oh! Chi è? ... È un asinello! Bravo!",
        "Senti questo: Squiiit squiiit! Chi fa questo verso? ... Un topolino! Piccolo piccolo!",
        "Beeee beeee! Chi è questo animale morbidoso? ... Una pecorella! Con tanta lana!",
        "Glu glu glu! Chi fa questo verso? ... Un tacchino! Con le piume colorate!",
    ],
    "imitate": [
        "Gioco dell'imitazione! Prova a fare il verso del gatto: miao miao! Riesci a farlo più acuto? E ora più grave? Bravissimo!",
        "Ora proviamo a imitare il leone! Fai un grande ruggito: ROAR! Più forte! ROAAAAR! Che leone coraggioso!",
        "Imitiamo il serpente: ssssss! Muovi la lingua come un serpentello. Sssssssss! Perfetto!",
        "Ora facciamo la scimmietta! Uuh uuh ah ah ah! Salta in giro come una scimmia! Che divertimento!",
        "Proviamo l'elefante! Fa il verso con la proboscide: PRUUUUU! E cammina con passi pesanti! BUM BUM BUM!",
        "Ora sei un uccellino! Cip cip cip! Apri le braccia come ali e fai finta di volare per la stanza!",
        "Facciamo il treno! Ciuf ciuf ciuf ciuf! Muovi le braccia come le ruote! Il treno parte dalla stazione!",
        "Ora imitiamo la pioggia! Tic tic tic con le dita sul tavolo. Piano piano, poi sempre più forte. Temporale!",
    ],
    "playful_english": [
        "Hello! Let's learn some colors! Red è rosso, blue è blu, green è verde, yellow è giallo. Riesci a ripetere? Red, blue, green, yellow! Bravissimo!",
        "Let's count! One, two, three, four, five! Uno, due, tre, quattro, cinque! Proviamo fino a dieci: six, seven, eight, nine, ten!",
        "Animals in English! Cat è gatto, dog è cane, bird è uccello, fish è pesce. Ripeti con me: cat, dog, bird, fish! Great job!",
        "What's your name? Mi chiamo... My name is... Come ti chiami? Prova a dire: My name is... e poi il tuo nome! Perfetto!",
        "Let's learn the family! Mom è mamma, dad è papà, sister è sorella, brother è fratello. Ripeti: mom, dad, sister, brother!",
        "Food time! Apple è mela, bread è pane, milk è latte, water è acqua. Yummy! Ripeti: apple, bread, milk, water!",
        "The days of the week! Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday! Proviamo insieme!",
        "How are you? Come stai? I'm fine è sto bene, I'm happy è sono felice. Come stai oggi? I'm happy! Bravissimo!",
    ],
    "logic_games": [
        "Gioco di logica numero uno! Ascolta bene la sequenza: uno, due, tre... Qual è il numero che viene dopo? ... Quattro! Bravo!",
        "Indovinello! Sono rotondo, sono arancione, e cresco sugli alberi. Cosa sono? ... Un'arancia! Esatto!",
        "Completa la sequenza: cerchio, quadrato, cerchio, quadrato, cerchio... Cosa viene dopo? ... Quadrato! Bravissimo!",
        "Ho quattro gambe ma non cammino. Puoi sederti su di me. Cosa sono? ... Una sedia! Giusto!",
        "Che giorno viene dopo lunedì? ... Martedì! E dopo martedì? ... Mercoledì! Perfetto!",
        "Se ho tre mele e ne mangio una, quante ne restano? ... Due! Bravo matematico!",
        "Indovinello: più sono grande, meno mi vedi. Cosa sono? ... Il buio! Che bravo!",
        "Quale animale è più grande: una formica o un elefante? ... L'elefante! E quale è più piccolo? La formica! Esatto!",
    ],
    "entertainment": [
        "Ciao amico! Oggi giochiamo insieme! Ti racconto una barzelletta: perché il pomodoro è diventato rosso? Perché ha visto l'insalata che si spogliava! Ah ah ah!",
        "Facciamo un gioco! Io dico una parola e tu dici il contrario. Grande! ... Piccolo! Alto! ... Basso! Caldo! ... Freddo! Sei bravissimo!",
        "Cantiamo insieme! Fra Martino, campanaro, dormi tu? Dormi tu? Suona le campane, suona le campane, din don dan, din don dan!",
        "Giochiamo a Vero o Falso! I pesci volano? ... Falso! Le mucche fanno muu? ... Vero! Il ghiaccio è caldo? ... Falso! Bravo!",
    ],
    "school": [
        "Lezione di scienze! Oggi parliamo del ciclo dell'acqua. L'acqua evapora dal mare, sale in cielo e forma le nuvole. Quando le nuvole sono piene, piove! E l'acqua torna nel mare. Che meraviglia la natura!",
        "Lezione di geografia! L'Italia è una penisola a forma di stivale. È circondata dal mare: il Mar Tirreno a ovest, l'Adriatico a est e lo Ionio a sud. La capitale è Roma!",
        "Lezione di matematica! Impariamo le tabelline del due. Due per uno fa due, due per due fa quattro, due per tre fa sei, due per quattro fa otto, due per cinque fa dieci!",
        "Lezione di storia! I dinosauri vivevano milioni di anni fa. Il più grande era il Brachiosaurus, alto come un palazzo! Il più famoso è il Tyrannosaurus Rex con i suoi denti enormi!",
    ],
    "ai_chat": [
        "Ciao! Sono il Gufetto Magico! Oggi non riesco a collegarmi a internet, ma posso comunque farti compagnia! Vuoi sentire una storia o preferisci un indovinello?",
        "Il Gufetto ti racconta una curiosità! Sapevi che i gufi possono girare la testa quasi completamente? Possono ruotarla di 270 gradi! Incredibile vero?",
        "Ecco un indovinello dal Gufetto! Ha le ali ma non è un uccello, ha le antenne ma non è una TV. Cosa è? ... Una farfalla! Bravissimo!",
        "Il Gufetto dice buongiorno! Lo sai che i gufi sono animali notturni? Dormono di giorno e sono svegli di notte. Per questo sono così saggi: hanno tanto tempo per pensare sotto le stelle!",
    ],
    "edu_ai": [
        "Lezione educativa! Oggi impariamo i cinque sensi. La vista per vedere, l'udito per sentire, l'olfatto per annusare, il gusto per assaggiare, e il tatto per toccare. Quanti sono? Cinque!",
        "Impariamo le forme! Il cerchio è rotondo come una palla. Il quadrato ha quattro lati uguali. Il triangolo ha tre lati. Il rettangolo è come un quadrato allungato!",
        "Lezione sulle stagioni! In primavera sbocciano i fiori, in estate fa caldo e si va al mare, in autunno cadono le foglie, e in inverno arriva la neve!",
        "Impariamo i colori primari! Rosso, giallo e blu sono i colori primari. Mescolando rosso e giallo otteniamo l'arancione! Giallo e blu fanno il verde! Rosso e blu fanno il viola!",
    ],
}

# =========================================================
# STATO DELLA GENERAZIONE IN BACKGROUND
# =========================================================

_generation_lock = threading.Lock()
_generation_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_mode": "",
    "generated": 0,
    "skipped": 0,
    "errors": [],
}


def get_generation_state() -> dict:
    """Ritorna una copia dello stato corrente della generazione."""
    with _generation_lock:
        return dict(_generation_state)


def _set_state(**kwargs):
    with _generation_lock:
        _generation_state.update(kwargs)


# =========================================================
# FUNZIONE PRINCIPALE DI GENERAZIONE
# =========================================================

def generate_offline_content(modes=None, force=False) -> dict:
    """
    Genera contenuti offline per le modalità specificate (o tutte).

    Args:
        modes: lista di mode da generare (None = tutte)
        force: se True, rigenera anche i file esistenti

    Returns:
        {"generated": int, "skipped": int, "errors": list, "details": dict}
    """
    from api.tts import synthesize_with_piper

    if modes is None:
        modes = list(OFFLINE_TEMPLATES.keys())

    # Filtra solo i mode validi
    modes = [m for m in modes if m in OFFLINE_TEMPLATES]

    total_files = sum(len(OFFLINE_TEMPLATES[m]) for m in modes)
    _set_state(
        running=True,
        progress=0,
        total=total_files,
        current_mode="",
        generated=0,
        skipped=0,
        errors=[],
    )

    generated = 0
    skipped = 0
    errors = []
    details = {}
    processed = 0

    try:
        for mode in modes:
            _set_state(current_mode=mode)
            texts = OFFLINE_TEMPLATES[mode]
            mode_dir = os.path.join(OFFLINE_FALLBACK_DIR, mode)
            os.makedirs(mode_dir, exist_ok=True)

            mode_generated = 0
            mode_skipped = 0
            mode_errors = []

            for idx, text in enumerate(texts, start=1):
                fname = f"{mode}_{idx:02d}.wav"
                out_path = os.path.join(mode_dir, fname)

                processed += 1
                _set_state(progress=processed)

                if not force and os.path.isfile(out_path):
                    log(f"Offline generator: skip existing {fname}", "info")
                    skipped += 1
                    mode_skipped += 1
                    continue

                try:
                    wav_path = synthesize_with_piper(text)
                    # Copia il file dalla cache Piper alla cartella offline
                    import shutil
                    shutil.copy2(wav_path, out_path)
                    log(f"Offline generator: generated {fname}", "info")
                    generated += 1
                    mode_generated += 1
                except RuntimeError as e:
                    err_msg = f"{mode}/{fname}: {e}"
                    log(f"Offline generator error: {err_msg}", "error")
                    errors.append(err_msg)
                    mode_errors.append(str(e))
                except Exception as e:
                    err_msg = f"{mode}/{fname}: {e}"
                    log(f"Offline generator unexpected error: {err_msg}", "error")
                    errors.append(err_msg)
                    mode_errors.append(str(e))

            details[mode] = {
                "generated": mode_generated,
                "skipped": mode_skipped,
                "errors": mode_errors,
            }

        _set_state(generated=generated, skipped=skipped, errors=errors)
    finally:
        _set_state(running=False, current_mode="", progress=processed, total=total_files)

    return {
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }


def list_offline_content() -> dict:
    """
    Elenca i contenuti offline disponibili per ogni mode.

    Returns:
        {mode: {"count": int, "files": [str]}}
    """
    result = {}
    for mode in OFFLINE_TEMPLATES:
        mode_dir = os.path.join(OFFLINE_FALLBACK_DIR, mode)
        if os.path.isdir(mode_dir):
            files = sorted(
                f for f in os.listdir(mode_dir)
                if f.lower().endswith(".wav") or f.lower().endswith(".mp3")
            )
        else:
            files = []
        result[mode] = {"count": len(files), "files": files}
    return result


def delete_offline_content(mode: str) -> dict:
    """
    Elimina i contenuti offline generati per un mode specifico.

    Args:
        mode: nome della modalità

    Returns:
        {"deleted": int, "mode": str}
    """
    import shutil

    if mode not in OFFLINE_TEMPLATES:
        raise ValueError(f"Mode non valido: {mode}")

    # Use the validated key from OFFLINE_TEMPLATES (not the raw user input)
    # to prevent any path-traversal risk when building the directory path.
    safe_mode = next(k for k in OFFLINE_TEMPLATES if k == mode)
    mode_dir = os.path.join(OFFLINE_FALLBACK_DIR, safe_mode)
    deleted = 0

    if os.path.isdir(mode_dir):
        for fname in os.listdir(mode_dir):
            # Only process plain audio filenames — no sub-paths
            clean_name = os.path.basename(fname)
            if clean_name.lower().endswith(".wav") or clean_name.lower().endswith(".mp3"):
                fpath = os.path.join(mode_dir, clean_name)
                try:
                    os.remove(fpath)
                    deleted += 1
                except OSError as e:
                    log(f"Offline generator: cannot delete {fpath}: {e}", "warning")

    return {"deleted": deleted, "mode": safe_mode}
