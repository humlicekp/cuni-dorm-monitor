# 🏛 CUNI Dormitory Capacity Monitor (Hlídač kolejí UK)

Automatický monitor volných kapacit na kolejích Univerzity Karlovy ([rehos.cuni.cz](https://rehos.cuni.cz)). 
Běží nepřetržitě na pozadí jako `systemd` služba a jakmile zjistí uvolněné lůžko ve sloupci **Muži** nebo **Neurčeno**, okamžitě odešle zprávu na Telegram s přímým odkazem na rezervaci.

---

## 🎯 Sledované koleje
1. **Kolej Hvězda** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380944`
2. **Kolej Budeč** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380942`
3. **Kolej Jednota** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380939`
4. **Kolej Na Větrníku** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380945`
5. **Kolej Švehlova** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380943`
6. **Kolej 17. listopadu** – `https://rehos.cuni.cz/crpp/eshop/collegeDetail/380948`

---

## 📱 Ovládání přímo z Telegramu

Bota můžete kompletně ovládat přímo z aplikace Telegram (příkazy se vám automaticky zobrazují i v nabídce pod tlačítkem `/`):

| Příkaz | Popis |
| :--- | :--- |
| `/check` | **Okamžitá kontrola** – Projde všechny koleje a vypíše aktuální stav do zprávy |
| `/status` | **Stav služby** – Zobrazí dobu běhu, čas poslední kontroly a interval |
| `/logs` | **Poslední logy** – Zobrazí posledních 15 řádků záznamu přímo v Telegramu |
| `/stop` | **Pozastavit** – Pozastaví automatické kontroly |
| `/start` | **Obnovit** – Obnoví automatické kontroly (nebo zobrazí úvodní zprávu) |
| `/restart` | **Restartovat** – Na dálku restartuje systémovou službu na ThinkPadu |
| `/help` | **Nápověda** – Vypíše přehled příkazů |

*Poznámka:* Bot z bezpečnostních důvodů reaguje výhradně na příkazy z vašeho autorizovaného účtu (`telegram_chat_id`).

---

## 🛠 Správa z terminálu (`manage.sh`)

| Příkaz | Popis |
| :--- | :--- |
| `./manage.sh start` | Spustí monitor na pozadí jako 24/7 systemd službu |
| `./manage.sh stop` | Zastaví monitor |
| `./manage.sh restart` | Restartuje monitor (např. po změně `config.json`) |
| `./manage.sh status` | Zobrazí stav služby v systemd |
| `./manage.sh logs` | Sledování živého výpisu logů (`journalctl`) |
| `./manage.sh check` | Jednorázová manuální kontrola všech kolejí v terminálu |
| `./manage.sh test` | Odešle zkušební zprávu na Telegram |
| `./manage.sh setup` | Průvodce nastavením tokenu a chat ID |
