import os.path, pipes, re, subprocess, tempfile, fnmatch
import sublime, sublime_plugin
from functools import partial
from .common import *

def abbreviate_user(path):
    """
    Return a path with the ~ dir abbreviated (i.e. the inverse of expanduser)
    """
    home_dir = os.path.expanduser("~")
    if path.startswith(home_dir):
        return "~" + path[len(home_dir):]
    else:
        return path


def settings():
    return sublime.load_settings('donatello.sublime-settings')

def save_settings():
    return sublime.save_settings('donatello.sublime-settings')


def cmd_settings(cmd):
    """
    Return the default settings with settings for the command merged in
    """
    d = {}
    for setting in ['exec_args', 'surround_cmd']:
        d[setting] = settings().get(setting)
    try:
        settings_for_cmd = next((c for c
                            in settings().get('cmd_settings')
                            if re.search(c['cmd_regex'], cmd)))
        d.update(settings_for_cmd)
    except StopIteration:
        pass
    return d


def parse_cmd(cmd_str):
    return re.match(
            r"\s*(?P<input>\|)?\s*(?P<shell_cmd>.*?)\s*(?P<output>[|>])?\s*$",
            cmd_str
        ).groupdict()


def run_cmd(cwd, cmd, wait, input_str=None):
    shell = isinstance(cmd, str)
    if wait:
        proc = subprocess.Popen(cmd, cwd=cwd,
                                     shell=shell,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     stdin=(subprocess.PIPE if input_str else None))
        encoded_input = None if input_str == None else input_str.encode('utf8')
        output, error = proc.communicate(encoded_input)
        return_code = proc.poll()
        if return_code:
            show_in_output_panel("`%s` exited with a status code of %s\n\n%s"
                                 % (cmd, return_code, error))
            return (False, None)
        else:
            return (True, output.decode('utf8'))
    else:
        subprocess.Popen(cmd, cwd=cwd, shell=shell)
        return (False, None)

def show_in_output_panel(message):
    window = sublime.active_window()
    panel_name = 'shell_turtlestein'
    panel = window.get_output_panel(panel_name)
    edit = panel.begin_edit()
    panel.insert(edit, 0, message)
    panel.end_edit(edit)
    window.run_command('show_panel', {'panel': 'output.' + panel_name})

def command_from_file_path(file_path):
    pattern = ".*/([^/]+)/(tests)/(.*)"
    matches=re.search(pattern, file_path)
    if matches:
        module=matches.group(1)
        fil=matches.group(3)
        return "rake 'test_only[{0}, {1}]'".format(module,fil)

def get_tmp_file_name(p):
    return(os.path.join(os.path.dirname(p) , ".tmp."+os.path.basename(p)))

def valid_test_file(p):
    file_name=os.path.basename(p)
    return file_name.startswith("test_") and file_name.endswith(".r")

def write_file(p,contents):
    f=open(p,'w')
    f.write(contents)
    f.close()

class ShellPromptCommand(sublime_plugin.WindowCommand):

    """
    Prompt the user for a shell command to run in the window's directory
    """
    def run(self, match="all"):
        cwd = cwd_for_window(self.window)
        view = self.window.active_view()
        sels = [sel.a for sel in view.sel()]
        file_name = view.file_name()
        view.run_command('save')
        if match == "repeat_last_test":
            sels=settings().get("selections",None)
            file_name = settings().get("last_test_file_path",None)
            match=settings().get("match",None)
            if match==None:
                return

        if match=="single_test":
            file_path = self.run_single(sels,file_name)
        else:
            file_path = file_name
        if file_path==None:
            return
        possible_command = command_from_file_path(file_path)
        if possible_command == None:
            return
        
        settings().set("selections",sels)
        settings().set("last_test_file_path",file_name)
        print("match")
        settings().set("match",match)
        save_settings()

        self.on_done(cwd, possible_command)

    def run_single(self,sels,file_name):
        if not valid_test_file(file_name):
            print("not valid test file")
            return
        test_code=self.slice_and_dice(file_name,sels)
        if test_code==None:
            print("no tests in current file")
            return
        tmp_filename=get_tmp_file_name(file_name)
        write_file(tmp_filename,test_code)
        return tmp_filename

    def slice_and_dice(self,file_name,selections):
        f=open(file_name,'r')
        text = f.read()
        search_pattern = r"test_that\("
        test_indices = [m.start() for m in re.finditer(search_pattern, text)]
        if test_indices==[]:
            return
        test_indices.append(len(text))
        test_locations=[]
        for sel in selections:
            test_location=test_indices[0]
            test_loc_index=0
            for x in test_indices[1:]:
                if x > sel:
                    break
                test_location = x
        return (text[0:test_indices[0]])+"\n"+(text[test_location:x])


    def on_done(self, cwd, cmd_str):
        cmd = parse_cmd(cmd_str)
        if not cmd['input'] and cmd['output'] == '|':
            sublime.error_message(
                "Piping output to the view requires piping input from the view as well."
                + " Please use a preceding |.")
            return

        active_view = self.window.active_view()
        if cmd['input'] or cmd['output'] == '|':
            if not active_view:
                sublime.error_message(
                    "A view has to be active to pipe text from and/or to a view.")
                return

        settings = cmd_settings(cmd['shell_cmd'])

        before, after = settings['surround_cmd']
        shell_cmd = before + cmd['shell_cmd'] + after

        if cmd['input']:
            input_regions = [sel for sel in active_view.sel() if sel.size() > 0]
            if len(input_regions) == 0:
                input_regions = [sublime.Region(0, active_view.size())]
        else:
            input_regions = None


        # We can leverage Sublime's (async) build systems unless we're
        # redirecting the output into a view. In that case, we use Popen
        # synchronously.
        if cmd['output']:
            for region in (input_regions or [None]):
                self.process_region(active_view, region, cwd, shell_cmd, cmd['output'])
        else:
            if input_regions:
                # Since Sublime's build system doesn't support piping to STDIN
                # directly, use a tempfile.
                text = "".join([active_view.substr(r) for r in input_regions])
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(text.encode('utf8'))
                shell_cmd = "%s < %s" % (shell_cmd, pipes.quote(temp.name))
            exec_args = settings['exec_args']
            exec_args.update({'cmd': shell_cmd, 'shell': True, 'working_dir': cwd})

            self.window.run_command("exec", exec_args)

    def process_region(self, active_view, selection, cwd, shell_cmd, outpt):
        input_str = None
        if selection:
            input_str = active_view.substr(selection)

        (success, output) = run_cmd(cwd, shell_cmd, True, input_str)
        if success:
            if outpt == '|':
                active_view.run_command("replace_with_text", {'region_start': selection.a,
                                                              'region_end': selection.b,
                                                              'text': output})
            elif outpt == '>':
                self.window.run_command("new_file")
                new_view = self.window.active_view()
                new_view.set_name(shell_cmd.strip())
                new_view.run_command("replace_with_text", {'text': output})
