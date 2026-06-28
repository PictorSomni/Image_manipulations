<?php
declare(strict_types=1);
session_start();

// Données hors du web root : public_html/journal/ → ../../journal_data/
define('DATA_DIR', dirname(__DIR__, 2) . '/journal_data/');
define('JOURNAL_FILE', DATA_DIR . 'journal.txt');
define('CONFIG_FILE', DATA_DIR . 'config.php');

function redirect(): void
{
    header('Location: ' . strtok($_SERVER['REQUEST_URI'], '?'));
    exit;
}

function page(string $title, string $body): void
{
    echo <<<HTML
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{$title}</title>
        <style>
            *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: Georgia, 'Times New Roman', serif;
                background: #222429;
                color: #c7ccd8;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 2.5rem 1rem 4rem;
            }
            h1 {
                font-size: 2.5rem;
                font-weight: normal;
                letter-spacing: .12em;
                text-transform: uppercase;
                color: #B587FE;
                margin-bottom: 2rem;
            }
            .card {
                width: 100%;
                max-width: 1100px;
            }
            input[type="password"] {
                width: 100%;
                padding: 1.25rem 1.5rem;
                background: #2C3038;
                border: 1px solid #373d4a;
                border-radius: 5px;
                color: #c7ccd8;
                font-size: 1.25rem;
                margin-bottom: .75rem;
                outline: none;
            }
            input[type="password"]:focus { border-color: #45B8F5; }
            textarea {
                width: 100%;
                padding: 1.25rem 1.5rem;
                background: #2C3038;
                border: 1px solid #373d4a;
                border-radius: 5px;
                color: #c7ccd8;
                font-family: Georgia, serif;
                font-size: 1.25rem;
                line-height: 1.75;
                resize: vertical;
                min-height: 180px;
                outline: none;
            }
            textarea:focus { border-color: #45B8F5; }
            button {
                margin-top: .75rem;
                padding: 1.25rem 1.5rem;
                background: #373d4a;
                border: 1px solid #45B8F5;
                border-radius: 5px;
                color: #45B8F5;
                font-size: 1.25rem;
                cursor: pointer;
                letter-spacing: .04em;
                transition: background .15s, color .15s;
            }
            button:hover { background: #45B8F5; color: #222429; }
            .error { color: #F17171; font-size: 1.25rem; margin-bottom: .75rem; }
            .hint { color: #9399A6; font-size: 1.25rem; margin-bottom: .5rem; }
            .history {
                width: 100%;
                max-width: 1100px;
                margin-bottom: 2.5rem;
                white-space: pre-wrap;
                word-break: break-word;
                line-height: 1.8;
                font-size: 1.25rem;
                background: #2C3038;
                border: 1px solid #373d4a;
                border-radius: 5px;
                padding: 1.25rem 1.5rem;
                max-height: 45vh;
                overflow-y: auto;
                color: #9399A6;
            }
            .history::-webkit-scrollbar { width: 5px; }
            .history::-webkit-scrollbar-track { background: #222429; }
            .history::-webkit-scrollbar-thumb { background: #373d4a; border-radius: 3px; }
            .empty { color: #373d4a; font-style: italic; }
            .logout {
                display: block;
                margin-top: 1.5rem;
                color: #9399A6;
                font-size: 1.25rem;
                text-decoration: none;
                text-align: center;
            }
            .logout:hover { color: #c7ccd8; }
            .sep { color: #45B8F5; }
        </style>
    </head>
    <body>
        <h1>Journal</h1>
        {$body}
    </body>
    </html>
    HTML;
}

// ─── Setup (premier lancement) ───────────────────────────────────────────────

if (!file_exists(CONFIG_FILE)) {
    $error = '';
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['pwd'])) {
        $pwd = $_POST['pwd'] ?? '';
        if (strlen($pwd) < 8) {
            $error = '<p class="error">Minimum 8 caractères.</p>';
        } else {
            if (!is_dir(DATA_DIR)) {
                mkdir(DATA_DIR, 0700, true);
            }
            $hash = password_hash($pwd, PASSWORD_DEFAULT);
            file_put_contents(CONFIG_FILE, '<?php define(\'PWD_HASH\', ' . var_export($hash, true) . ');');
            file_put_contents(DATA_DIR . '.htaccess', "Deny from all\n");
            redirect();
        }
    }
    page('Journal — Configuration', <<<HTML
        <div class="card">
            {$error}
            <p class="hint" style="margin-bottom:1rem">Premier lancement — choisis ton mot de passe.</p>
            <form method="post">
                <input type="password" name="pwd" placeholder="Mot de passe (8 caractères min.)" autofocus minlength="8">
                <button type="submit">Créer le journal</button>
            </form>
        </div>
    HTML);
    exit;
}

require CONFIG_FILE;

// ─── Déconnexion ─────────────────────────────────────────────────────────────

if (isset($_GET['logout'])) {
    session_destroy();
    redirect();
}

// ─── Connexion ───────────────────────────────────────────────────────────────

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['password'])) {
    if (password_verify($_POST['password'], PWD_HASH)) {
        $_SESSION['auth'] = true;
        redirect();
    }
    $_SESSION['login_error'] = true;
    redirect();
}

if (!($_SESSION['auth'] ?? false)) {
    $error = '';
    if ($_SESSION['login_error'] ?? false) {
        unset($_SESSION['login_error']);
        $error = '<p class="error">Mot de passe incorrect.</p>';
    }
    page('Journal', <<<HTML
        <div class="card">
            {$error}
            <form method="post">
                <input type="password" name="password" placeholder="Mot de passe" autofocus>
                <button type="submit">Ouvrir</button>
            </form>
        </div>
    HTML);
    exit;
}

// ─── Ajout d'une entrée ──────────────────────────────────────────────────────

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['entry'])) {
    $text = trim($_POST['entry'] ?? '');
    if ($text !== '') {
        file_put_contents(
            JOURNAL_FILE,
            "\n\n{$text}",
            FILE_APPEND | LOCK_EX
        );
    }
    redirect();
}

// ─── Affichage ───────────────────────────────────────────────────────────────

$raw     = file_exists(JOURNAL_FILE) ? file_get_contents(JOURNAL_FILE) : '';
$history = trim($raw);
$today   = date('d/m/Y');
$uri     = strtok($_SERVER['REQUEST_URI'], '?');

if ($history === '') {
    $history_html = '<span class="empty">Aucune entrée pour le moment.</span>';
} else {
    $history_html = htmlspecialchars($history, ENT_QUOTES, 'UTF-8');
}

$prefill = htmlspecialchars("— {$today} —\n\n", ENT_QUOTES, 'UTF-8');

page('Journal', <<<HTML
    <div class="history">{$history_html}</div>
    <div class="card">
        <p class="hint">Nouvelle entrée</p>
        <form method="post">
            <textarea name="entry" id="entry">{$prefill}</textarea>
            <button type="submit">Enregistrer</button>
        </form>
        <a class="logout" href="{$uri}?logout">Déconnexion</a>
    </div>
    <script>
        const t = document.getElementById('entry');
        t.focus();
        t.setSelectionRange(t.value.length, t.value.length);
        t.scrollTop = t.scrollHeight;
    </script>
HTML);
