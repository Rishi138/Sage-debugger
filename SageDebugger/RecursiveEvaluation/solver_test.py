from solver import SageAgentModel
model = SageAgentModel()
dummy_instance = {
    "instance_id": 0,
    "repo": "numpy/numpy",
    "problem_statement": "Fix off-by-one error in sum function",
    "context": ""
}

bash_cmd = model.generate(dummy_instance)
print(bash_cmd)
