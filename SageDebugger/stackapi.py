import requests

# stack overflow search algorithim code
# specific query
sample_q1 = "urllib3 v2.0 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with LibreSSL 2.8.3"
# semi-specific query
sample_q2 = "openai python chatcompletion object is not subscriptable"
# broad query
sample_q3 = "openai key not working"


def search(error_message):
    response = requests.get(
        'https://api.stackexchange.com/2.3/search/excerpts?order=desc&sort=activity&q={}&site=stackoverflow'.format(
            error_message
        )
    )

    if response.status_code != 200:
        print("Error fetching Stack Overflow results!")

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
        'https://api.stackexchange.com/2.3/questions/{}?order=desc&sort=activity&site=stackoverflow&filter=withbody'
        .format(post_id)
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
        'https://api.stackexchange.com/2.3/questions/{}/answers?order=desc&sort=votes&site=stackoverflow&filter=withbody'
        .format(post_id)
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


print(ask(sample_q1))

