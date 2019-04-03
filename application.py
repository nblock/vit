#!/usr/bin/env python

from future.utils import raise_

import subprocess

import urwid

from util import clear_screen, string_to_args, is_mouse_event
from process import Command
from task import TaskListModel
from task_list import TaskTable, SelectableRow, TaskListBox
import event
from command_bar import CommandBar

PALETTE = [
    ('list-header', 'black', 'white'),
    ('reveal focus', 'black', 'dark cyan', 'standout'),
]

class Application():
    def __init__(self, config, task_config, reports, report):

        self.config = config
        self.task_config = task_config
        self.reports = reports
        self.report = report
        self.command = Command(self.config)
        self.event = event.Emitter()
        self.event.listen('command-bar:keypress', self.command_bar_keypress)
        self.run(self.report)

    def command_bar_keypress(self, data):
        metadata = data['metadata']
        op = metadata['op']
        if 'choices' in data['metadata']:
            choice = data['choice']
            if op == 'quit' and choice:
                self.quit()
            elif op == 'done' and choice is not None:
                if self.model.task_done(metadata['uuid']):
                    self.update_report()
            elif op == 'start-stop' and choice is not None:
                if self.model.task_start_stop(metadata['uuid']):
                    self.update_report()
            elif op == 'priority' and choice is not None:
                if self.model.task_priority(metadata['uuid'], choice):
                    self.update_report()
        elif data['key'] in ('enter'):
            args = string_to_args(data['text'])
            if op == 'ex':
                self.ex(data['text'], data['metadata'])
            elif len(args) > 0:
                if op == 'add':
                    self.execute_command(['task', 'add'] + args)
                elif op == 'modify':
                    # TODO: Will this break if user clicks another list item
                    # before hitting enter?
                    self.execute_command(['task', metadata['uuid'], 'modify'] + args)
                elif op == 'project':
                    # TODO: Validation if more than one arg passed.
                    if self.model.task_project(metadata['uuid'], args[0]):
                        self.update_report()
                elif op == 'tag':
                    if self.model.task_tags(metadata['uuid'], args):
                        self.update_report()
                elif op == 'wait':
                    # TODO: Validation if more than one arg passed.
                    returncode, stdout, stderr = self.command.run(['task', metadata['uuid'], 'modify', 'wait:%s' % args[0]], capture_output=True)
                    if returncode == 0:
                        self.update_report()
                    else:
                        # TODO: Error handling.
                        raise_(ValueError, "Error setting wait: %s" % stderr)
        self.widget.focus_position = 'body'

    def key_pressed(self, key):
        if is_mouse_event(key):
            return None
        # TODO: Should be 'ZZ'.
        if key in ('Q', 'Z'):
            self.quit()
        elif key in ('a'):
            self.activate_command_bar('add', 'Add: ')
        elif key in ('u'):
            self.execute_command(['task', 'undo'])
        elif key in ('q'):
            self.activate_command_bar('quit', 'Quit?', {'choices': {'y': True}})
        elif key in ('t', ':'):
            edit_text = '!rw task ' if key in ('t') else None
            self.activate_command_bar('ex', ':', edit_text=edit_text)

    def on_select(self, row, size, key):
        if is_mouse_event(key):
            return key
        if key in ('m'):
            uuid = self.get_focused_task()
            if uuid:
                self.activate_command_bar('modify', 'Modify: ', {'uuid': uuid})
            return None
        if key in ('b'):
            uuid = self.get_focused_task()
            if uuid:
                task = self.model.get_task(uuid)
                if task:
                    task_id = task['id']
                    self.activate_command_bar('start-stop', '%s task %s? (y/n): ' % (task.active and 'Stop' or 'Start', task_id), {'uuid': uuid, 'choices': {'y': True}})
            return None
        if key in ('d'):
            uuid = self.get_focused_task()
            if uuid:
                task = self.model.get_task(uuid)
                if task:
                    task_id = task['id']
                    self.activate_command_bar('done', 'Mark task %s done? (y/n): ' % task_id, {'uuid': uuid, 'choices': {'y': True}})
            return None
        if key in ('P'):
            uuid = self.get_focused_task()
            if uuid:
                choices = {
                    'h': 'H',
                    'm': 'M',
                    'l': 'L',
                    'n': '',
                }
                self.activate_command_bar('priority', 'Priority (h/m/l/n): ', {'uuid': uuid, 'choices': choices})
        if key in ('p'):
            uuid = self.get_focused_task()
            if uuid:
                self.activate_command_bar('project', 'Project: ', {'uuid': uuid})
            return None
        if key in ('T'):
            uuid = self.get_focused_task()
            if uuid:
                self.activate_command_bar('tag', 'Tag: ', {'uuid': uuid})
            return None
        if key in ('w'):
            # TODO: Detect if task is already waiting, if so do confirm to un-wait.
            uuid = self.get_focused_task()
            if uuid:
                self.activate_command_bar('wait', 'Wait: ', {'uuid': uuid})
            return None
        if key in ('e'):
            self.execute_command(['task', row.uuid, 'edit'])
            return None
        if key in ('=', 'enter'):
            self.execute_command(['task', row.uuid, 'info'], update_report=False)
            return None
        elif key in ('ctrl l'):
            self.update_report()
        return key

    def ex(self, text, metadata):
        args = string_to_args(text)
        if len(args):
            command = args.pop(0)
            if command in ('q'):
                self.quit()
            elif command in ('!', '!r', '!w', '!rw', '!wr'):
                kwargs = {}
                if command in ('!', '!w'):
                    kwargs['update_report'] = False
                if command in ('!', '!r'):
                    kwargs['confirm'] = None
                self.execute_command(args, **kwargs)
            else:
                # TODO: Display error message.
                pass

    def get_focused_task(self):
        if self.widget.focus_position == 'body':
            try:
                return self.task_list.focus.uuid
            except:
                pass
        return False

    def quit(self):
        raise urwid.ExitMainLoop()

    def build_report(self):
        self.model = TaskListModel(self.task_config, self.reports, self.report)
        self.table = TaskTable(self.task_config, self.reports[self.report], self.model.tasks, on_select=self.on_select)

        self.header = urwid.Pile([
            urwid.Text('Welcome to PYT'),
            self.table.header,
        ])
        self.footer = CommandBar(event=self.event)

    def execute_command(self, args, **kwargs):
        update_report = True
        if 'update_report' in kwargs:
            update_report = kwargs['update_report']
            kwargs.pop('update_report')
        self.loop.stop()
        self.command.result(args, **kwargs)
        if update_report:
            self.update_report()
        self.loop.start()

    def activate_command_bar(self, op, caption, metadata={}, edit_text=None):
        metadata['op'] = op
        self.footer.activate(caption, metadata, edit_text)
        self.widget.focus_position = 'footer'

    def update_report(self, report=None):
        self.build_main_widget(report)
        self.loop.widget = self.widget

    def build_main_widget(self, report=None):
        if report:
            self.report = report
        self.build_report()
        self.widget = urwid.Frame(
            self.table.listbox,
            header=self.header,
            footer=self.footer,
        )
        self.task_list = self.widget.body

    def run(self, report):
        self.build_main_widget(report)
        self.loop = urwid.MainLoop(self.widget, PALETTE, unhandled_input=self.key_pressed)
        self.loop.run()
