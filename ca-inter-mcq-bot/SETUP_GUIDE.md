# CA Inter Daily MCQ Bot – Setup Guide (ఒక్కసారి చేస్తే చాలు)

ఈ bot రోజూ **10:50 AM** కి 4 mini-cases + 4 polls, **1:50 PM** కి answers ఆటోమేటిక్‌గా మీ group కి పంపుతుంది.
GitHub delay వల్ల posts దాదాపు 11:00 AM / 2:00 PM కి వస్తాయి. ఇది GitHub లో **ఫ్రీ** గా నడుస్తుంది. మీ PC ఆన్‌లో ఉండాల్సిన అవసరం లేదు.

## ఈ folder లో ఏమున్నాయి

| File | ఏం చేస్తుంది |
|---|---|
| `bot.py` | Bot program |
| `plan.json` | రోజువారీ MCQs (ఇప్పుడు 20 రోజులు, రోజుకు 4 subjects). ఇవి అయిపోయేలోపు Claude కొత్తవి add చేస్తుంది. |
| `config.json` | Settings: answer time label, anonymous polls, case pin, skip days |
| `state.json` | ఏ రోజు వరకు పంపామో గుర్తుపెట్టుకుంటుంది. దీన్ని మార్చకండి. |
| `.github/workflows/` | రోజూ ఏ టైంకి రన్ అవ్వాలో ఇక్కడ ఉంటుంది (4 workflows) |

---

## Step 1 – GitHub అకౌంట్
1. https://github.com/signup లో ఫ్రీ అకౌంట్ తెరవండి.
2. (Claude తో ఫైల్స్ upload చేయించాలంటే) claude.ai → **Settings → Connectors** → **GitHub** connect చేయండి. ఇది చేస్తే Step 2 Claude చేస్తుంది.

## Step 2 – Repository create చేసి ఫైల్స్ upload చేయడం
1. GitHub లో కుడి పైన **+** → **New repository** ఎంచుకోండి.
2. Name: `ca-inter-mcq-bot` → **Private** ఎంచుకోండి → **Create repository**.
3. ఆ పేజీలో **"uploading an existing file"** link మీద click చేయండి.
4. ఈ folder లోని **అన్ని ఫైల్స్, `.github` folder తో సహా** drag & drop చేయండి → **Commit changes**.
5. Upload అయ్యాక `.github/workflows` లో 4 ఫైల్స్ కనిపించాలి. ఒకసారి చెక్ చేయండి.

## Step 3 – Bot Token ని Secret గా పెట్టడం
1. Repo లో **Settings → Secrets and variables → Actions** ఓపెన్ చేయండి.
2. **New repository secret** click చేయండి.
3. Name: `BOT_TOKEN`, Secret: BotFather ఇచ్చిన token → **Add secret**.

Token ఇక్కడ lock అవుతుంది. ఎవరికీ (Claude కి కూడా) కనిపించదు.

## Step 4 – Group ID కనుక్కోవడం
1. Telegram లో మీ bot కి private గా `/start` పంపండి.
2. మీ group లో ఏదైనా ఒక మెసేజ్ పెట్టండి.
3. GitHub repo లో **Actions** tab ఓపెన్ చేయండి. Workflows enable చేయమని అడిగితే enable చేయండి.
4. **"0. Find group ID"** ఎంచుకుని → **Run workflow** click చేయండి.
5. Run పూర్తయ్యాక దాన్ని ఓపెన్ చేసి → **find** → **"List chats the bot can see"** లోకి వెళ్ళండి. అక్కడ ఇలా కనిపిస్తుంది:
   ```
   private    'మీ పేరు'          CHAT_ID = 987654321
   supergroup 'CA Inter Group'   CHAT_ID = -1001234567890
   ```
6. Group కి Topics ఉంటే, ఆ topic లో ఒక మెసేజ్ పెట్టి మళ్ళీ రన్ చేయండి. అప్పుడు `TOPIC_ID` కూడా కనిపిస్తుంది.

## Step 5 – ముందు మీ private chat లో టెస్ట్ (students కి ఏమీ వెళ్ళదు)
1. Step 3 లాగానే ఇంకో secret పెట్టండి: Name `CHAT_ID`, Value = **మీ private** CHAT_ID (ఉదా: `987654321`).
2. **Actions → "1. Post daily MCQs" → Run workflow** చేయండి. మీ private chat లో Day 1 4 mini-cases + 4 polls వస్తాయి.
3. Polls కి మీరే vote చేయండి. తర్వాత **"2. Post answers" → Run workflow** చేయండి. Answers + % వస్తాయి.
4. అంతా బాగుంటే **Actions → "9. Reset progress" → Run workflow** చేయండి. దీంతో bot మళ్ళీ Day 1 నుంచి మొదలవుతుంది.

## Step 6 – Live (అసలు group)
1. `CHAT_ID` secret ని update చేయండి: Value = **group** CHAT_ID (`-100…`).
2. Topics వాడుతుంటే: **Settings → Secrets and variables → Actions → Variables** tab → **New repository variable** → Name `TOPIC_ID`, Value = topic నంబర్.
3. ఇంతే. మరుసటి రోజు 11 AM నుంచి ఆటోమేటిక్‌గా మొదలవుతుంది.

---

## తర్వాత ఏదైనా మార్చాలంటే
- **కొత్త MCQs:** Claude కొత్త రోజులు `plan.json` లో add చేస్తుంది. Bot ఆగకుండా కొనసాగుతుంది.
- **ఆదివారం off:** `config.json` లో `"skip_weekdays": ["Sun"]` అని పెట్టాలి.
- **Answers 3 PM కి:** `.github/workflows/2-post-answers.yml` లో cron `"20 9 * * *"` గా మార్చాలి, `config.json` లో `"answer_time_label": "3:00 PM"` గా మార్చాలి.
- **ఒక రోజు ఆపాలంటే:** Actions → workflow → **⋯ → Disable workflow**.
- **Token లీక్ అయితే:** BotFather లో `/revoke` చేసి కొత్త token తీసుకోండి, తర్వాత `BOT_TOKEN` secret update చేయండి.

ఏదైనా పని చేయకపోతే Actions లో ఎర్ర ❌ ఉన్న run ని ఓపెన్ చేసి, ఆ error message ని Claude కి పంపండి.
