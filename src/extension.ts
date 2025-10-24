import * as vscode from 'vscode';

export function getSessionContext(): string {
  const editor = vscode.window.activeTextEditor;
  const terminal = vscode.window.activeTerminal;
  let context = '';
	if (editor) {
	const doc = editor.document;
	const fullText = doc.getText();
	const selectedText = editor.selection.isEmpty ? '' : doc.getText(editor.selection);
	const language = doc.languageId;
	const filename = doc.uri.fsPath;

	context += `filename: ${filename}\n`;
	context += `language: ${language}\n`;
	if (selectedText) {
		context += `selection:\n${selectedText}\n\n`;
	}
	context += `code:\n${fullText}\n`;

	const diagnostics = vscode.languages.getDiagnostics(doc.uri);
	if (diagnostics.length > 0) {
		context += `\ndiagnostics:\n`;
		diagnostics.forEach((d, i) => {
		const severity = ['Error', 'Warning', 'Information', 'Hint'][d.severity] || 'Unknown';
		context += `${i + 1}. [${severity}] Line ${d.range.start.line + 1}: ${d.message}\n`;
		});
	} else {
		context += `\ndiagnostics:\nNone\n`;
	}
	}
  return context;
}



export function activate(context: vscode.ExtensionContext) {
	vscode.window.showInformationMessage("Sage is Active")

	const disposable = vscode.commands.registerCommand('sage.helloWorld', () => {
		vscode.window.showInformationMessage('Hello World from Sage!');
		console.log(getSessionContext())
	});

	const focusMainView = vscode.commands.registerCommand("sage.focusMainView", () => {
		vscode.commands.executeCommand("sage.mainView.focus");
	})

	const provider = new mainViewProvider(context.extensionUri);
	context.subscriptions.push(
		vscode.window.registerWebviewViewProvider(mainViewProvider.viewType, provider),
		focusMainView
	);

	vscode.commands.executeCommand("sage.mainView.focus");
}


export function deactivate() {}


class mainViewProvider implements vscode.WebviewViewProvider {
	public static readonly viewType = "sage.mainView";
	private _view?: vscode.WebviewView;

	constructor(
		private readonly _extensionUri: vscode.Uri,
	) {}

	public resolveWebviewView(
		webviewView: vscode.WebviewView,
		_context: vscode.WebviewViewResolveContext,
		_token: vscode.CancellationToken,
	) {
		webviewView.webview.onDidReceiveMessage((msg) => {
		if (msg.command === 'getContext') {
			const payload = getSessionContext();
			webviewView.webview.postMessage({ type: 'context', data: payload });
		}
		});

		this._view = webviewView;
		webviewView.webview.options = {
			enableScripts: true,
			localResourceRoots: [
				this._extensionUri
			]
		};

		webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);
	}

	private _getHtmlForWebview(webview: vscode.Webview) {
		const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, "media", "main.js"));
		const styleMainUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'main.css'));
		return `
			<!DOCTYPE html>
			<html lang="en">
			<head>
			<meta charset="UTF-8" />
			<meta name="viewport" content="width=device-width, initial-scale=1.0" />
			<title>Sage Chat</title>
			<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500&display=swap" rel="stylesheet" />
			<link href="${styleMainUri}" rel="stylesheet">
			</head>
			<body>
			<div class="chat-container">
				<div class="chat-header">
				<div class="title">Sage</div>
				<div class="thread-id" onclick="changeThread()">Thread: #a829X</div>
				</div>
				<div id="chat-messages" class="chat-messages">
				<div class="bot-message starter-message">Hi! I'm Sage — your coding assistant. Ask me anything to get started.</div>
				</div>
				<div class="chat-input-container">
				<textarea id="user-input" rows="1" placeholder="Type your message..."></textarea>
				<button id="send-btn">➤</button>
				</div>
			</div>

			<script src="${scriptUri}"></script>
			</body>
			</html>
	`
	}	
}