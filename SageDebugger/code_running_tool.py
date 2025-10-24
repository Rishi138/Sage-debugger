import io
import time
import contextlib
import traceback

# function takes in code as str and returns dict
def execute_code(code: str) -> dict:
    # create in memory stream
    output = io.StringIO()
    # set the error to none initially
    error = None
    # get start time
    start_time = time.time()

    # tries to execute the code
    try:
        # executes the code put output goes to the stream instead of our console
        with contextlib.redirect_stdout(output):
            exec(code, {})
    # catches exception
    except:
        error = traceback.format_exc()

    # gets end time to calculate runtime
    end_time = time.time()
    runtime = round(end_time - start_time, 4)

    # return results
    return {
        "output": output.getvalue(),
        "error": error,
        "runtime": f"{runtime}s"
    }

