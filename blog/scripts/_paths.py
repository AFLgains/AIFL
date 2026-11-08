"""Where the figure scripts read from and write to. Figures are made from the private checkout's data; only the
small JSON they produce is published. Set AFL_SIM_HOME if that checkout is not at C:\\projects\\afl_sim."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
HOME = os.environ.get("AFL_SIM_HOME", r"C:\projects\afl_sim")
sys.path[:0] = [os.path.join(HOME, "src"), os.path.join(HOME, "experiments", "value_function")]
os.chdir(HOME)
os.makedirs(ASSETS, exist_ok=True)
