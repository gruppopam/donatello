import sublime, sublime_plugin
import glob
import os
import os.path
from .common import *

index={}

class TheNavigatorCommand(sublime_plugin.WindowCommand):
    def run(self):
        fs=getallfiles(cwd_for_window(self.window))
        for f in fs:
            build_index(f)
        print(index)
        

# def build_index():

def getallfiles(dir, extn = ".r"):
    fs=[]
    for root, dirs, files in os.walk(dir):
        for file in files:
            if file.endswith(extn):
                fs.append(os.path.join(root, file))
    return fs

def build_index(file):
    f=open(file,"r")
    text = f.read()
    search_pattern = r"([a-zA-Z0-9\_]+) *(=|<-|<<-) *(function\(.*?\))"
    print(file)
    for match in re.finditer(search_pattern, text):
        index[match.group(1)] = index.get(match.group(1)) or []
        index[match.group(1)].append([match.start(),match.group(3),file])
    f.close()
