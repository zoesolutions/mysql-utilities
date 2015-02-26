#
# Copyright (c) 2010, 2015, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#

"""
clone_server_parameters test.
"""

import os
import subprocess
import stat
import time

import mutlib

from mysql.utilities.common.server import Server
from mysql.utilities.exception import UtilError, MUTLibError

CANNOT_START_SERVER_ERR = ("Cannot connect to server restarted with the "
                           "startup command generated by mysqlserverclone.")


class test(mutlib.System_test):
    """clone server parameters
    This test exercises the parameters for mysqlserverclone for server versions
    after and including MySQL 5.7.6.
    """

    start_cmd_fl = None

    def check_prerequisites(self):
        has_server = self.check_num_servers(1)
        srv = self.servers.get_server(0)
        if not srv.check_version_compat(5, 7, 6):
            raise MUTLibError("Test requires server version 5.7.6 and later.")
        return has_server

    def setup(self):
        # No setup needed
        self.start_cmd_fl = os.path.join(os.getcwd(),
                                         ("restart_server.bat"
                                          if os.name == 'nt'
                                          else "restart_server.sh"))
        return True

    def _test_server_clone(self, cmd_str, comment, kill=True,
                           capture_all=False, restart=None):
        """Test server clone.

        cmd_str[in]       Command to be executed.
        comment[in]       Test comment.
        kill[in]          True for kill process.
        capture_all[in]   True for capture all rows.
        restart[in]       True for restart server.
        """
        quote_char = "'" if os.name == "posix" else '"'
        self.results.append(comment + "\n")
        port1 = int(self.servers.get_next_port())
        cmd_str = "{0} --new-port={1} ".format(cmd_str, port1)
        full_datadir = os.path.join(os.getcwd(),
                                    "temp with spaces".format(port1))
        cmd_str = "{0} --new-data={2}{1}{2} --delete ".format(cmd_str,
                                                              full_datadir,
                                                              quote_char)
        res = self.exec_util(cmd_str, "start.txt")
        with open("start.txt") as f:
            for line in f:
                # Don't save lines that have [Warning] or don't start with #
                index = line.find("[Warning]")
                if capture_all or (index <= 0 and line[0] == '#'):
                    self.results.append(line)
        if res:
            raise MUTLibError("{0}: failed".format(comment))

        # Create a new instance
        conn = {"user": "root", "passwd": "root", "host": "localhost",
                "port": port1}

        server_options = {'conn_info': conn, 'role': "cloned_server_2"}
        new_server = Server(server_options)
        if new_server is None:
            return False
        if kill:
            # Connect to the new instance
            try:
                new_server.connect()
            except UtilError:
                new_server = None
                raise MUTLibError("Cannot connect to spawned server.")
            drop = False if restart else True
            self.servers.stop_server(new_server, drop=drop)
            # if restart, try to use the generated script to restart the
            # server.
            if restart:
                if os.name == 'posix':
                    #Change file permissions
                    fl_st = os.stat(self.start_cmd_fl)
                    os.chmod(self.start_cmd_fl, fl_st.st_mode | stat.S_IEXEC)
                # This sleep gives a chance to the OS to unlock the server
                # files before restart the server.
                time.sleep(3)
                run_script = restart
                with open("restart.txt", 'a+') as f_out:
                    if self.debug:
                        print
                        print("executing script: {0}".format(run_script))
                        subprocess.Popen(run_script)
                    else:
                        subprocess.Popen(run_script, stdout=f_out,
                                         stderr=f_out)
                # Reconnect to the instance after restart it
                max_tries, attempt = 3, 0
                while attempt < max_tries:
                    try:
                        time.sleep(3)
                        new_server.connect()
                        break
                    except UtilError:
                        attempt += 1
                else:  # if while is exhausted
                    new_server = None
                    raise MUTLibError(CANNOT_START_SERVER_ERR)
                self.servers.stop_server(new_server)

        return True

    def run(self):
        self.res_fname = "result.txt"
        base_cmd = ("mysqlserverclone.py --server={0} "
                    "--root-password=root ".format(
                        self.build_connection_string(
                            self.servers.get_server(0))))
        os_quote = '"' if os.name == 'nt' else "'"
        #  (comment, command options, kill running server, restart_with_cmd)
        test_cases = [
            ("show help", " --help ", False, True, False),
            ("write command to file", " --write-command=startme.sh ",
             True, False, False),
            ("write command to file shortcut", " -w startme.sh ",
             True, False, False),
            ("verbosity = -v", " -v ", True, False, False),
            ("verbosity = -vv", " -vv ", True, False, False),
            ("verbosity = -vvv", " -vvv ", True, False, False),
            ("-vvv and write command to file shortcut",
             " -vvv -w startme.sh ", True, False, False),
            ("write command to file and run it",
             " -w {0} ".format(self.start_cmd_fl), True, False,
             self.start_cmd_fl),
            ("use --skip-innodb",
             ("--mysqld={0}--skip-innodb --default-storage-engine=MYISAM "
              "--default-tmp-storage-engine=MYISAM{0}".format(os_quote)),
             True, False, False),
            ("use --innodb", "--mysqld={0}--innodb{0}".format(os_quote),
             True, False, False),
        ]

        test_num = 1
        for row in test_cases:
            new_comment = "Test case {0} : {1}".format(test_num, row[0])
            if not self._test_server_clone("{0}{1}".format(base_cmd, row[1]),
                                           new_comment, row[2], row[3],
                                           row[4]):
                raise MUTLibError("{0}: failed".format(new_comment))
            test_num += 1

        # Perform a test using the --user option for the current user
        user = None
        try:
            user = os.environ['USERNAME']
        except KeyError:
            user = os.environ['LOGNAME']
        finally:
            if not user:
                raise MUTLibError("Cannot obtain user name for test case.")

        comment = "Test case {0}: - User the --user option".format(test_num)
        if not self._test_server_clone("{0}--user={1}".format(base_cmd, user),
                                       comment, True, False):
            raise MUTLibError("{0}: failed".format(comment))
        test_num += 1

        self.replace_result("#  -uroot", "#  -uroot [...]\n")
        self.replace_result("#                       mysqld:",
                            "#                       mysqld: XXXXXXXXXXXX\n")
        self.replace_result("#                   mysqladmin:",
                            "#                   mysqladmin: XXXXXXXXXXXX\n")
        self.replace_result("# Cloning the MySQL server running on ",
                            "# Cloning the MySQL server running on "
                            "XXXXX-XXXXX.\n")

        self.remove_result("# trying again...")
        # Since it may or may not appear, depending on size of path, remove it
        self.remove_result("# WARNING: The socket file path '")

        # Remove version information
        self.remove_result_and_lines_after("MySQL Utilities "
                                           "mysqlserverclone version", 6)

        return True

    def get_result(self):
        return self.compare(__name__, self.results)

    def record(self):
        return self.save_result_file(__name__, self.results)

    @staticmethod
    def _remove_file(filename):
        """Remove file.

        filename[in]   Filename to be removed.
        """
        try:
            os.unlink(filename)
        except OSError:
            pass

    def cleanup(self):
        files = [self.res_fname, "start.txt", "startme.sh", self.start_cmd_fl,
                 "restart.txt"]
        for file_ in files:
            self._remove_file(file_)
        return True
