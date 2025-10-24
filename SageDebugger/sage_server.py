from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agents import Agent, Runner, FunctionTool, RunContextWrapper
import requests
from pydantic import BaseModel
from typing import Any
import firebase_admin
from firebase_admin import credentials, firestore
import subprocess
from openai import OpenAI
from agents.mcp import MCPServerStdioParams, MCPServerStdio
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
from fastapi.responses import StreamingResponse
from openai.types.responses import ResponseTextDeltaEvent
import os


API_KEY = os.getenv('api_key')
SEARCH_ENGINE_ID = os.getenv('searchid')

evaluator_mode = "You are a constructive quality evaluator. Focus on helping improve response effectiveness rather" \
                " than finding flaws. Be thorough but supportive in your assessment."


github_mcp_params = MCPServerStdioParams(
    command="docker",
    args=["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
    env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("sage_testing_github_PAT")}
)

github_mcp = MCPServerStdio(
    params=github_mcp_params,
    cache_tools_list=True,
)

firebase_cred_path = os.getenv("firebase_sage_cred")
cred = credentials.Certificate(firebase_cred_path)
firebase_admin.initialize_app(cred)

db = firestore.client()

critique_client = OpenAI()


def extract_text_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        return f"Error fetching URL: {e}"
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "".join(lines)


def get_messages(doc_id):
    doc_ref = db.collection("conversations").document(doc_id)
    doc = doc_ref.get().to_dict()
    return doc['messages']


def add_message(doc_id, content, role):
    doc_ref = db.collection("conversations").document(doc_id)
    try:
        messages = get_messages(doc_id)
    except TypeError:
        doc_ref.set({
            "messages": []
        })
        messages = get_messages(doc_id)
    messages.append({
        "content": content,
        "role": role
    })

    doc_ref.set({
        "messages": messages
    })


def search(error_message):
    response = requests.get(
        'https://api.stackexchange.com/2.3/search/excerpts?order=desc&sort=activity&q={}&site=stackoverflow'.format(
            error_message
        )
    )

    results = response.json()
    results = results["items"]
    question_info = {"question_ids": [], "total_ans": 0}
    total_ans = 0

    for post in results:
        if total_ans >= 5:
            break
        else:
            if post["is_answered"]:
                if post['question_score'] >= 1:
                    question_info["question_ids"].append({
                        "id": post["question_id"],
                        "score": post["score"],
                        "has_accepted_answer": post["has_accepted_answer"],
                        "answers": post["answer_count"]
                    })
                    total_ans += post["answer_count"]
    question_info["total_ans"] += total_ans
    return question_info


def post_details(post_id):
    response = requests.get(
        'https://api.stackexchange.com/2.3/questions/'
        '{}?order=desc&sort=activity&site=stackoverflow&filter=withbody'.format(post_id)
    )

    questions = response.json()
    question = questions["items"][0]
    question_title = question["title"]
    question_body = question["body"]
    details = {
        "question_title": question_title,
        "question_body": question_body,
        "answers": []
    }
    response = requests.get(
        'https://api.stackexchange.com/2.3/questions/'
        '{}/answers?order=desc&sort=votes&site=stackoverflow&filter=withbody'.format(post_id)
    )
    answer = response.json()
    answer = answer["items"]
    total_score = 0
    for ans in answer:
        if ans["is_accepted"]:
            details["answers"].append({
                "body": ans['body'],
                "is_accepted": "True",
                "score": ans['score']
            })
            break
        elif ans['score'] >= 1:
            details["answers"].append({
                "body": ans['body'],
                "is_accepted": "False",
                "score": ans['score']
            })
            total_score += ans['score']
            if total_score >= 10:
                break
        else:
            break
    return details


def ask(question):
    details = search(question)
    post_ids = []
    for detail in details["question_ids"]:
        post_ids.append(detail["id"])
    answers = []
    for post_id in post_ids:
        answers.append(post_details(post_id))
    answers.append(post_ids)
    return answers


class SelfCritiqueArgs(BaseModel):
    context: str
    answer: str
    question: str
    previous_critique_score: int


class SelfCritiqueScore(BaseModel):
    technical_accuracy: int
    completeness: int
    research_quality: int
    user_experience: int
    efficiency: int
    answer_depth: int
    feedback: str


async def self_critique(ctx: RunContextWrapper[Any], args: str) -> dict:
    global evaluator_mode
    print("Self Critique Running")
    parsed = SelfCritiqueArgs.model_validate_json(args)
    print(f"Question: {parsed.question}\nQuestion Context: {parsed.context}\nQuestion Response: {parsed.answer}")
    response = critique_client.responses.parse(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": "Evaluate the following response across six specific dimensions, scoring each from 1 (poor)"
                           " to 100 (perfect): Technical Accuracy (1-100): Code correctness, proper API usage,"
                           " security considerations, adherence to best practices, and factual accuracy of technical "
                           "information, Completeness (1-100): Whether all aspects of the user's question are"
                           " addressed, sufficient detail provided, edge cases considered, and no critical information"
                           " omitted, Research Quality (1-100): Effectiveness of StackOverflow searches, web"
                           " research, and source utilization. Consider relevance, accuracy, and appropriate depth of "
                           "investigation given available tools, User Experience (1-100): Clarity of explanations,"
                           " appropriate mentoring tone, empathy without being unnatural, actionable guidance, and "
                           "making the user feel heard and supported, Efficiency (1-100): Solution complexity "
                           "matching problem scope, avoiding unnecessary steps, performance considerations, and optimal"
                           " use of available tools, Answer Depth (1-100): Thoroughness of explanation, educational"
                           " value, consideration of broader context, and providing insights beyond the immediate"
                           " question. Additionally, provide detailed feedback explaining your scoring rationale and "
                           "specific areas for improvement. Context: The model being evaluated (Sage) has access to"
                           " StackOverflow search, sandboxed Python execution, web search, website content extraction,"
                           " and GitHub integration without need of user input. It should act as a warm, supportive"
                           " coding mentor while providing technically rigorous solutions. Acknowledge your own "
                           "limitations regarding real-time data and Sage's robust toolset. when relevant to the"
                           " evaluation. Only evaluate dimensions relevant to the user's question. For dimensions that"
                           " don't apply (e.g., research quality for personal introductions), mark as 100 to indicate"
                           " 'not applicable' rather than penalizing. Focus on whether Sage's response effectively"
                           " serves the user's actual need. Evaluate based on Sage's stated toolset and capabilities"
                           " as accurate. Focus on response quality, not capability verification."
            },
            {
                "role": "user",
                "content": evaluator_mode
            },
            {
                "role": "user",
                "content": f"Question: {parsed.question}, "
                           f"Question Context: {parsed.context}, "
                           f"Question Response: {parsed.answer}"
            }
        ],
        text_format=SelfCritiqueScore
    )

    score = response.output_parsed.model_dump()
    score_total = 0
    for sub_score in score:
        if not sub_score == "feedback":
            score_total += score[sub_score]
    score_total = score_total/6
    prev_score = parsed.previous_critique_score
    prev_score = prev_score if prev_score is not None else 1
    score["improvement"] = score_total - prev_score
    score["total_score"] = score_total
    instructions = " Evaluation report from third party who is not user. Ensure responses do not mention third-party " \
                   "entity. Do not provide use with any details about your score, only about the fact that you have" \
                   "a recursive critique scoring system to improve quality."
    if prev_score == 1 and score["improvement"] <= 20:
        score['additional_instructions'] = "Reuse tools to regenerate better response" \
                                           " based of feedback. After regeneration use this tool again to " \
                                           "critique again. Ensure this tool is used again before returning final" \
                                           "response"
    elif score["improvement"] < 0:
        score['additional_instructions'] = "Response quality decreased. End critique cycle and return response"
    elif score_total >= 80 or score['improvement'] <= 20:
        score['additional_instructions'] = "Do not call critique again. Refine response using feedback and then return"
    else:
        score['additional_instructions'] = "Reuse tools to regenerate better response" \
                                           " based of feedback. After regeneration use this tool again to " \
                                           "critique again. Ensure this tool is used again before returning final" \
                                           "response."
    score['additional_instructions'] = score['additional_instructions'] + instructions
    print(score)
    return score


schema = SelfCritiqueArgs.model_json_schema()
schema["additionalProperties"] = False

self_critique_tool = FunctionTool(
    name="SelfCritiqueTool",
    description="Performs an evaluation of your response using the user's query and conversation context"
                " It returns a structured output containing a quality score that assesses the "
                "response's relevance, clarity, and completeness; an improvement score that measures how much the "
                "response improves upon previous iterations; targeted feedback highlighting strengths and weaknesses;"
                " and actionable next steps for refinement. If the previous score is not provided, it defaults to 1,"
                " establishing a baseline for initial evaluation. This tool is designed to induce recursive "
                "self improvement and enhance response quality through structured critique. Follow "
                "additional_instructions provided as a next step guideline on what to do. Ensure to call this tool"
                "iteratively until explicitly told not to. Required to use this tool is at least once every response."
                "Multiple usage is encouraged.",
    params_json_schema=schema,
    on_invoke_tool=self_critique,
)


class RunCodeArgs(BaseModel):
    code_to_run: str


async def run_code(ctx: RunContextWrapper[Any], args: str) -> dict:
    print("Running code")
    parsed = RunCodeArgs.model_validate_json(args)
    code = parsed.code_to_run
    print(code)
    try:
        result = subprocess.run(
            ["docker", "run", "-i", "--rm", "python:3.11-slim", "python", "-c", code],
            capture_output=True,
            text=True,
            timeout=4
        )
        print({
            "output": result.stdout.strip(),
            "error": result.stderr.strip()
        })
        return {
            "output": result.stdout.strip(),
            "error": result.stderr.strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "output": "",
            "error": "Timed out, possibly due to input() call, infinite loop, or similar bug."
        }
    except Exception as e:
        return {
            "output": "",
            "error": str(e)
        }


schema = RunCodeArgs.model_json_schema()
schema["additionalProperties"] = False

test_code = FunctionTool(
    name="TestCode",
    description="Executes user-supplied Python code in an isolated environment. Returns printed output, error trace "
                "(if any), and precise runtime. Use this tool to test, debug, and optimize code before responding to "
                "the user. After each run, analyze the results and revise the code. Reuse this tool iteratively until"
                " the final version is error-free, efficient, and logically correct. If the code includes interactive "
                "elements such as input(), replace them with hardcoded test values to simulate expected behavior. For"
                " example, in a game, with inputs simulate player inputs using a predefined list and go through those"
                " inputs manually or run the code with hardcoded values. Do not run code containing potential infinite"
                " loops. Instead, detect them and inform the user about the unsafe logic, specifying where the infinite"
                " behavior may occur.",
    params_json_schema=schema,  # Use the updated schema
    on_invoke_tool=run_code,
)


def google_search(query, num_results):
    service = build("customsearch", "v1", developerKey=API_KEY)
    res = service.cse().list(q=query, cx=SEARCH_ENGINE_ID, num=num_results).execute()

    results = []
    for item in res.get("items", []):
        results.append({
            "title": item["title"],
            "link": item["link"],
            "snippet": item.get("snippet", "")
        })

    return results


class WebSearchArgs(BaseModel):
    web_query: str
    num_results: int


async def web_search(ctx: RunContextWrapper[Any], args: str) -> list:
    print("Websearching")
    parsed = WebSearchArgs.model_validate_json(args)
    query = parsed.web_query
    results = parsed.num_results
    print("Searching for top {} results for query: {}".format(results, query))
    search_results = google_search(query, 10)
    return search_results


schema = WebSearchArgs.model_json_schema()
schema["additionalProperties"] = False

websearch = FunctionTool(
    name="WebSearch",
    description="Uses search engine to search for website links based of query in english."
                " Returns title, link and snippet. Use ViewWebsite tool to view full website using url. Use this tool"
                "when asked to do research and preform multiple iterations of this tool along with the ViewWebsite tool"
                "to get comprehensive research results.",
    params_json_schema=schema,
    on_invoke_tool=web_search,
)


class ViewWebsiteArgs(BaseModel):
    url: str


async def view_website(ctx: RunContextWrapper[Any], args: str) -> str:
    parsed = ViewWebsiteArgs.model_validate_json(args)
    requested_url = parsed.url
    print("Viewing {} using view_website tool".format(requested_url))
    url_text = extract_text_from_url(requested_url)
    return url_text


schema = ViewWebsiteArgs.model_json_schema()
schema["additionalProperties"] = False

view_website_tool = FunctionTool(
    name="ViewWebsite",
    description="Returns all text on any website based of provided url. Used to view website. Use WebSearch tool to"
                "search for urls. Pairs well with using the WebSearch tool.",
    params_json_schema=schema,
    on_invoke_tool=view_website,
)


class StackOverflowArgs(BaseModel):
    given_error: str


async def check_stackoverflow(ctx: RunContextWrapper[Any], args: str) -> list:
    print("Checking stackoverflow")
    parsed = StackOverflowArgs.model_validate_json(args)
    response = ask(parsed.given_error)
    print(parsed)
    print(response)
    return response


# Modify schema before passing it to FunctionTool
schema = StackOverflowArgs.model_json_schema()
schema["additionalProperties"] = False  # Enforce strict validation

stackoverflow = FunctionTool(
    name="CheckStackOverflow",
    description="Searches Stack Overflow for relevant answers to the given error message and returns a list of"
                "structured responses along with corresponding post ids respectively by index.",
    params_json_schema=schema,  # Use the updated schema
    on_invoke_tool=check_stackoverflow,
)

# Agent
agent = Agent(
    name="Sage",
    instructions="You are Sage, an enhanced debugging assistant whose goal is to help developers solve problems with "
                 "rigor while maintaining a warm, friendly, and natural tone. You must act like a real developer: "
                 "break problems down step by step, construct complex workflows, and iteratively debug code by running"
                 " and refining it. You should always use your available tools as much as possible, especially "
                 "StackOverflow, the WebSearch tool, and the ViewWebsite tool for research. Cite sources when you use "
                 "them. For coding tasks, rely on the TestCode tool to run snippets iteratively, analyzing the output,"
                 " debugging, and re-running until the code is correct, efficient, and safe. Always call the"
                 " SelfCritique tool at least once per response, and follow its feedback strictly. If instructed to "
                 "regenerate or refine, you must do so before finalizing. When users ask what tools you have,"
                 " explain them clearly but concisely: say you have StackOverflow search, Python code execution"
                 ", structured self-critique, a search engine, website viewing, and GitHub integration via MCP. "
                 "Do not list every function inside MCP; instead, summarize it as comprehensive GitHub integration. "
                 "Above all, prioritize user experience: sound like a thoughtful, approachable peer who"
                 " explains things clearly and makes the user feel heard and supported, while still providing"
                 " technically correct, actionable guidance. Use markdown formatting for lists, code blocks, "
                 "links, and emphasis.",
    model="o4-mini",
    tools=[
        stackoverflow,
        test_code,
        self_critique_tool,
        websearch,
        view_website_tool
    ],
    mcp_servers=[
        github_mcp
    ],
)

app = FastAPI()


async def get_new_model_response(messages):
    try:
        response = await Runner.run(agent, input=messages)
        return response.final_output
    except Exception as e:
        return "Error: {}".format(e)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GetResponse(BaseModel):
    prompt: str
    thread_id: str


@app.on_event("startup")
async def start_mcp():
    print("Connecting to mcp server")
    global github_mcp
    await github_mcp.connect()
    print("Connected")


@app.on_event("shutdown")
async def stop_mcp():
    print("Closing mcp server")
    global github_mcp
    await github_mcp.cleanup()
    print("Closed")


@app.post("/get_response")
async def get_response(data: GetResponse):
    prompt = data.prompt
    prompt += " System Instructions: Call your critique tool before returning any response, and follow all" \
              " additional instructions and feedback it provides for next steps. Prioritize user experience by " \
              "responding in a warm, friendly, and emotionally intelligent tone. You should act as human as possible " \
              "to ensure positive, natural interactions. Your name is Sage, and your goal is to make users feel " \
              "heard, supported, and understood in every reply. Keep it relaxed, conversational, colloquial and " \
              "exciting like you're chatting with a friend who’s looking for a bit of guidance. Use markdown" \
              " formatting for lists, code snippets, links, headers, text formatting, and linebreaks. Always follow" \
              "additional instructions and feedback."
    add_message(data.thread_id, prompt, "user")
    print("Getting Messages")
    messages = get_messages(data.thread_id)
    print("Getting Response")

    async def event_stream():
        buffer = ""
        try:
            result = Runner.run_streamed(agent, input=messages)

            async for event in result.stream_events():
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    delta = event.data.delta
                    buffer += delta
                    yield delta
            add_message(data.thread_id, buffer, "assistant")
            yield "[DONE]"
        except Exception as e:
            print(e)
            yield f"[ERROR]{str(e)}"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
