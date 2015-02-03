#!/usr/bin/env python

from __future__ import print_function

import argparse
import fileinput
import json
from json import JSONEncoder,JSONDecoder
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

""" This is a utility to manage an OE build directory.
"""

class LayerSerializer:
    """ Class to serialize a collection of Repo objects into LAYERS form.
    """
    def __init__(self, repos):
        self._repos = []
        for repo in repos:
            if type(repo) is Repo:
                self._repos.append(repo)
            else:
                raise TypeError
    def write(self, fd=sys.stdout):
        """ Write the LAYERS file to the specified file object.
        """
        for repo in self._repos:
            fd.write("{0} {1} {2} {3}\n".format(repo._name, repo._url, repo._branch, repo._revision))

class BBLayerSerializer:
    """ Class to serialize a collection of Repo objects into bblayer form.
    """
    def __init__(self, base, repos=[]):
        """ Initialize class.

        base: Directory component relative to TOPDIR where repos live.
              For repos in ${TOPDIR}/repos the base would be 'repos'.
        repos: An optional list of Repo objects. These objects hold all the
               interesting data that's written to the bblayers.conf file.
        """
        self._base = base
        self._repos = []
        for repo in repos:
            if type(repo) is Repo:
                self._repos.append(repo)
            else:
                raise TypeError
    def add_repo(self, repo):
        """ Add Repo object to be written to the bblayers.conf file.

        repo: The Repo object that's being added to the BBLayerSerializer.
        """
        self._repos.append(repo)
    def write(self, fd=sys.stdout):
        """ Write the bblayers.conf file to the specified file object.

        fd: A file object where the bblayer.conf file will be written.
            The default is sys.stdout.
        """
        fd.write("LCONF_VERSION ?= \"5\"\n")
        fd.write("BBPATH ?= \"${TOPDIR}\"\n")
        fd.write("BBLAYERS ?= \" \\\n")
        for repo in self._repos:
            if repo._layers is not None:
                for layer in repo._layers:
                    fd.write("    ${{TOPDIR}}/{0}/{1}/{2} \\\n".format(self._base, repo._name, layer))
        fd.write("\"\n")

class RepoFetcher(object):
    """ Class to manage git repo state.
    """
    def __init__(self, base, repos=[]):
        """ Initialize class.

        base: Directory where repos will or currently do reside.
        repos: List of Repo objects for the RepoFetcher to operate on.
        """
        self._base = base
        self._repos = []
        for repo in repos:
            if type(repo) is Repo:
                self._repos.append(repo)
            else:
                raise TypeError
    def add_repo(self, repo):
        """ Add a repo to the RepoFetcher.
        """
        self._repos.append(repo)
    def __str__(self):
        """ Create a string representation of all Repos in the RepoFetcher.
        """
        return ''.join(str(repo) for repo in self._repos)
    def clone(self):
        """ Clone all repos in a RepoFetcher.

        Does nothing more than loop over the list of Repo objects invoking the
        'clone' method on each.
        """
        for repo in self._repos:
            repo.clone(self._base)

class Repo(object):
    """ Data required to clone a git repo in a specific state.
    """
    def __init__(self, name, url, branch="master", revision="head", layers=["./"]):
        """ Initialize Repo object.

        name: Sting name of the repo.
        url: URL where git repo lives.
        brance: Branch that will be checked out. Default is 'master'.
        revision: Revision where HEAD should point. Default is 'HEAD'.
        layers: A list of the OE meta-layers in the repo that we care about.
                By default we assume the base of the repo is the root of the
                meta layer but in some cases the repo may contain many, or none
                at all. In this last case layers should be set to None.
        """
        self._name = name
        self._url = url
        self._branch = branch
        self._revision = revision
        self._layers = layers
    def set_branch(self, branch):
        """ Set branch for Repo object.
        """
        self._branch = branch
    def set_revision(self, revision):
        """ Set revision for Repo object.
        """
        self._revision = revision
    def set_layers(self, layers):
        """ Set the list of layers for the Repo ojbect.
        """
        self._layers = layers
    def __str__(self):
        """ Create a human readable string representation of the Repo object.
        """
        return ("name:     {0}\n"
                "url:      {1}\n"
                "branch:   {2}\n"
                "revision: {3}\n"
                "layers:   {4}\n".format(self._name, self._url, self._branch,
                                         self._revision,self._layers))
    def clone(self, path):
        """ Clone the Repo.

        path: Path where Repo will be cloned. If renative it will be relative
              to $(pwd).
        """
        dest = path + "/" + self._name
        try:
            if not os.path.exists(dest):
                print("cloning {0} into {1}".format (self._name, path))
                return subprocess.call(
                    ['git', 'clone', '--progress', self._url, dest], shell=False
                )
            else:
                raise EnvironmentError("Cannot clone {0} to {1}: directory exists".format(self._name, dest))
        except subprocess.CalledProcessError, e:
            print(e)
 
class FetcherEncoder(JSONEncoder):
    """ Encode RepoFetcher object as JSON

    Pass this class to the dumps function from the json module along with your
    RepoFetcher object.
    """
    def default(self, obj):
        """ Iterate over repo objects from RepoFetcher encoding each as JSON.
            Return the result in a list.

        obj: RepoFetcher that's being encoded as JSON.
        """
        if type(obj) is not RepoFetcher:
            raise TypeError
        if obj._repos is None:
            raise ValueError
        list_tmp = []
        for repo in obj._repos:
            list_tmp.append(RepoEncoder().default(repo))
        return list_tmp

class RepoEncoder(JSONEncoder): 
    """ Encode a Repo object as JSON

    Pass this class to the dumps function from the json module along with your
    Repo object.
    """
    def default(self, obj):
        """ Encode a Repo object into a form suitable for serialization as
            JSON. Basically this turns the Repo object into a native python
            dictionary since those can be serialized to JSON.

        obj: Repo object to be encoded.
        """
        if type(obj) is not Repo:
            raise TypeError
        dict_tmp = {}
        dict_tmp["name"] = obj._name
        dict_tmp["url"] = obj._url
        if obj._branch != "master":
            dict_tmp["branch"] = obj._branch
        if obj._layers is None:
            dict_tmp["layers"] = obj._layers
        elif len(obj._layers) > 1 or obj._layers[0] != "./":
            dict_tmp["layers"] = obj._layers
        return dict_tmp

class PathSanity(dict):
    """ Sanity check and nomalize parameters.
    """
    def __init__(self, topdir):
        super(PathSanity, self).__init__(self)
        if os.path.isdir(topdir):
            self._topdir = os.path.abspath(os.path.realpath(topdir))
        else:
            raise ValueError("topdir parmater does not exist")
    def __setitem__(self, name, value):
        tmp = os.path.abspath(os.path.realpath(value))
        if tmp.startswith(self._topdir):
            dict.__setitem__(self, name, tmp)
        else:
            raise ValueError("parameter {0} is not under topdir".format(name))
    def __getitem__(self, name):
        return dict.__getitem__(self, name)

def repo_decode(json_obj):
    """ Create a repository object from a dictionary.

    Intended for use in JSON deserialization.
    json_obj: A dictionary object that contains a serialized Repo object.
    """
    if type(json_obj) is not dict:
        raise TypeError
    return Repo(json_obj["name"],
                     json_obj["url"],
                     json_obj.get("branch", "master"),
                     json_obj.get("revision", "HEAD"),
                     json_obj.get("layers", ["./"]))

def layers_from_bblayers(top_dir, bblayers_fd):
    """ Parse the layers from the bblayers.conf file

    top_dir: The absolute path to replace occurrences of TOPDIR in the
             bblayers.conf file.
    bblayers_fd: A file object attached to the bblayers.conf file
    """
    front = ""
    while True:
        cur = bblayers_fd.read(1)
        if not front.endswith("BBLAYERS"):
            front += cur
        else:
            break
    # Gobble till first quote
    while True:
        cur = bblayers_fd.read(1)
        if cur == '\"':
            break
    # collect all characters till the next quote
    layers = ""
    while True:
        cur = bblayers_fd.read(1)
        if cur == '\"' and not layers.endswith('\\'):
            break
        else:
            if cur == '\n':
                layers += ' '
            else:
                layers += cur

    # strip newlines and extra whitespace
    tmp =  " ".join(layers.replace("${TOPDIR}", top_dir).split())
    return tmp

def repo_state(git_dir):
    """ Collect the url, branch and revision of the parameter git repo

    git_dir: The file path to a local git clone.
    returns a tripple (url, branch, rev)
    """
    rev = subprocess.check_output(
        ["git", "--git-dir", git_dir, "rev-parse", "HEAD"]
    ).rstrip()
    branch = subprocess.check_output(
        ["git", "--git-dir", git_dir, "rev-parse", "--abbrev-ref", "HEAD"]
    ).rstrip()
    remote = subprocess.check_output(
        ["git", "--git-dir", git_dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    ).split("/")[0].rstrip()
    url = subprocess.check_output(
        ["git", "--git-dir", git_dir, "config", "--get", "remote." + remote + ".url"]
    ).rstrip()
    return url, branch, rev

def repos_from_state(bblayers_file, top_dir="./", src_dir="./sources"):
    """ Build a list of Repo objects from current build state.

    This requires that we do a few things:
    1) determine the state of the git repos checked out
    2) determine which layers are active by parsing bblayers.conf
    3) figure out which layer comes from which repo

    bblayers_file: path to bblayers file
    sources: path to directory holding all of the relevant repos
    """
    top_dir = os.path.abspath(top_dir)
    src_dir = os.path.abspath(src_dir)
    # Get layers from bblayers.conf
    with open(bblayers_file, 'r') as bblayers_fd:
        layers = layers_from_bblayers(top_dir, bblayers_fd)
 
    # Create Repo objects from repos in src_dir
    repos = []
    subdirs = os.listdir(src_dir)
    for item in subdirs:
        repo_root = os.path.join(src_dir, item)
        git_dir = os.path.join(repo_root, ".git")
        # check that directory is a git repo
        if os.path.isdir(git_dir):
            # collect data from git repo
            url, branch, rev = repo_state(git_dir)
            # get layers in the repo we're processing
            metas = []
            for thing in subprocess.check_output(
                ["find", repo_root, "-name", "layer.conf"]
            ).strip().split('\n'):
                if os.path.exists(thing):
                    metas.append(thing)

            # find layers that are active in each repo 
            repo_layer = []
            for layer in metas:
                layer = os.path.dirname(os.path.dirname(layer))
                if layer in layers:
                    # strip leading directory component from layer path
                    # including directory separator character
                    repo_layer.append(layer[len(repo_root) + 1:])

            if repo_layer == []:
                repo_layer = None
            repos.append(Repo(item, url, branch=branch, revision=rev, layers=repo_layer))
    return repos
 
def json_gen(args):
    """ Parse bblayers.conf and collect data from repos in src_dir to generate
        a json file representing their state.
    """
    top_dir = os.path.abspath(args.top_dir)
    conf_dir = os.path.join(top_dir, "conf")
    bblayers_file = os.path.join(conf_dir, "bblayers.conf")
    src_dir = os.path.join(top_dir, args.src_dir)
    json_out_file = os.path.join(top_dir, args.json_out)

    # build a list of Repo objects and create a fetcher for them
    repos = repos_from_state(bblayers_file, top_dir=top_dir, src_dir=src_dir)
    fetcher = RepoFetcher(src_dir, repos=repos)
    # Serialize Repo objects to JSON manifest
    with open(json_out_file, 'w') as repo_json_fd:
        json.dump(fetcher, repo_json_fd, indent=4, cls=FetcherEncoder)

def layers_gen(args):
    """ Collect data from repos in src_dir to generate the LAYERS file.
    """
    top_dir = os.path.abspath(args.top_dir)
    if not os.path.isabs(args.src_dir):
        src_dir = os.path.join(top_dir, args.src_dir)
    else:
        src_dir = os.path.abspath(args.src_dir)
    if not os.path.isabs(args.bblayers_file):
        bblayers_file = os.path.join(top_dir, args.bblayers_file)
    else:
        bblayers_file = os.path.abspath(args.bblayers_file)
    if not os.path.isabs(args.layers_file):
        layers_file = os.path.join(top_dir, args.layers_file)
    else:
        layers_file = os.path.abspath(args.layers_file)

    # create list of Repo objects
    repos = repos_from_state(bblayers_file, top_dir=top_dir, src_dir=src_dir)

    # create LAYERS file
    layers = LayerSerializer(repos)
    with open(layers_file, 'w') as layers_fd:
        layers.write(fd=layers_fd)

def manifest(args):
    """ Create manifest describing current state of repos in src_dir.

    top_dir: The root directory of the build.
    """
    # need sanity tests for paths / names
    top_dir = os.path.abspath(args.top_dir)
    conf_dir = os.path.join(top_dir, "conf")
    archive_prefix = args.archive
    archive_file = os.path.join(top_dir, archive_prefix + ".tar.bz2")
    bblayers_file = os.path.join(conf_dir, "bblayers.conf")
    localconf_file = os.path.join(conf_dir, "local.conf")
    environment_sh_file = os.path.join(top_dir, "environment.sh")
    build_sh_file = os.path.join(top_dir, "build.sh")
    fetch_sh_file = os.path.join(top_dir, "fetch.sh")
    layers_file = os.path.join(top_dir, "LAYERS")

    # collect build config files and tar it all up
    # make temporary directory
    tmp_dir = tempfile.mkdtemp()
    # mk conf dir
    os.mkdir(os.path.join(tmp_dir, "conf"))
    # copy local.conf to tmp/conf/local.conf
    shutil.copy(bblayers_file, os.path.join(tmp_dir, "conf"))
    shutil.copy(localconf_file, os.path.join(tmp_dir, "conf"))
    # copy environment.sh to tmp/
    shutil.copy(environment_sh_file, os.path.join(tmp_dir, "environment.sh"))
    # copy build.sh to tmp/
    shutil.copy(build_sh_file, os.path.join(tmp_dir, "build.sh"))
    # copy fetch.sh to tmp/
    shutil.copy(fetch_sh_file, os.path.join(tmp_dir, "fetch.sh"))
    # copy LAYERS to tmp
    shutil.copy(layers_file, os.path.join(tmp_dir, "LAYERS"))

    # tar it all up
    with tarfile.open(archive_file, "w:bz2") as tar:
        tar.add(tmp_dir, arcname=archive_prefix, recursive=True)

    return

def setup(args):
    """ Setup build structure.
    """
    top_dir = os.path.abspath(args.top_dir)
    build_type = args.build_type
    build_file_src = os.path.join(top_dir, "build_" + build_type + ".sh")
    build_file_dst = os.path.join(top_dir, "build.sh")
    conf_dir = os.path.join(top_dir, "conf")
    src_dir_abs = os.path.join(top_dir, "source")
    src_dir_rel = "sources"
    layers_file = os.path.join(top_dir, "LAYERS")

    # sanity test for generated files that have already been created
    # do this before generating any files to prevent leaving thigns half done
    local_conf = os.path.join(conf_dir, "local.conf")
    if os.path.exists(local_conf):
        raise ValueError("generated file already exists: " + local_conf)
    local_conf_orig = os.path.join(conf_dir, "local_" + build_type + ".conf")
    if not os.path.exists(local_conf_orig):
        raise ValueError("no config to copy: " + local_conf_orig)

    env_sh = os.path.join(top_dir, "environment.sh")
    if os.path.exists(env_sh):
        raise ValueError("generated file already exists: " + env_sh)
    env_sh_template = os.path.join(top_dir, "environment.sh.template")
    if not os.path.exists(env_sh_template):
        raise ValueError("no template to copy: " + sh_env_template)

    bblayers_file = os.path.join(conf_dir, "bblayers.conf")
    if os.path.exists(bblayers_file):
        raise ValueError(bblayers_file + " already exists")

    if os.path.exists(layers_file):
        raise ValueError(layers_file + " already exists")

    if os.path.exists(build_file_dst):
        raise ValueError(build_file_dst + " already exists")

    # Parse JSON file with repo data
    repo_json = "LAYERS_" + build_type + ".json"
    with open(repo_json, 'r') as repos_fd:
        while True:
            try:
                repos = JSONDecoder(object_hook=repo_decode).decode(repos_fd.read())
                fetcher = RepoFetcher(src_dir_abs, repos=repos)
            except ValueError:
                break;
    # create bblayers.conf file
    if not os.path.isdir(conf_dir):
        os.mkdir(conf_dir)
    bblayers = BBLayerSerializer(src_dir_rel, repos=fetcher._repos)
    with open(bblayers_file, 'w') as test_file:
        bblayers.write(fd=test_file)

    # create LAYERS file
    layers = LayerSerializer(fetcher._repos)
    with open(layers_file, 'w') as layers_fd:
        layers.write(fd=layers_fd)

    # copy local_type.conf -> local.conf
    shutil.copy(local_conf_orig, local_conf)

    # generate environment.sh
    shutil.copy(env_sh_template, env_sh)
    os.chmod(env_sh, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IWOTH)
    for line in fileinput.input(env_sh, inplace=1):
        line = re.sub("@sources@", src_dir_rel, line.rstrip())
        print(line)

    # copy build script
    shutil.copy(build_file_src, build_file_dst)
    os.chmod(build_file_dst, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IWOTH)

    return

def fetch_repos(args):
    """ Clone repos and set them to the state described by the LAYERS.json file
    """
    update = args.update
    try:
        paths = PathSanity(args.top_dir)
        paths["src_dir"] = args.src_dir
        paths["json_in"] = args.json_in
    except ValueError as e:
        print(e)
        sys.exit(1)

    if not os.path.isfile(paths["json_in"]):
        raise ValueError("json_in does not exist, run \'setup\' action or specify the file explicitly")

    # Parse JSON file with repo data
    with open(paths["json_in"], 'r') as repos_fd:
        while True:
            try:
                repos = JSONDecoder(object_hook=repo_decode).decode(repos_fd.read())
                fetcher = RepoFetcher(paths["src_dir"], repos=repos)
            except ValueError:
                break;

    if not os.path.exists(paths["src_dir"]):
        os.mkdir(paths["src_dir"])

    try:
        if not update:
            fetcher.clone()
        else:
            raise NotImplementedError()
    except EnvironmentError as e:
        print(e)
        sys.exit(1)

def main():
    description = "Manage OE build infrastructure."
    repos_json_help = "A JSON file describing the state of the repos."
    action_help = "An action to perform on the build directory."
    bblayers_help = "Path to the bblayer.conf file."
    conf_dir_help = "Directory where all local bitbake configs live."
    manifest_help = "Generate tarball for reproducing build."
    setup_help = "Setup the OE build directory. This includes cloning the " \
            "repos from the JSON file and creating the bblayers.conf " \
            "file."
    source_dir_help = "Checkout git repos into this directory."
    top_dir_help = "Root of build directory. This is TOPDIR in OE. Defaults " \
            "to the current working directory."
    build_type_help = "The type of the build to setup."
    json_gen_help = "Parse bblayers.conf and git repos in source dir to generate JSON file describing the build."
    json_out_help = "File to write JSON representation of the build state to."
    archive_file_help = "Prefix for build archive file name."
    layers_file_help = "File it write LAYERS representation of the build state to."
    layers_gen_help = "Parse git repos in source dir to generate LAYERS file describing the build."

    parser = argparse.ArgumentParser(prog=__file__, description=description)
    actionparser = parser.add_subparsers(help=action_help)
    # parser for 'setup' action
    setup_parser = actionparser.add_parser("setup", help=setup_help)
    setup_parser.add_argument("-b", "--build-type", default="core", help=build_type_help)
    setup_parser.add_argument("-t", "--top-dir", default=os.getcwd(), help=top_dir_help)
    setup_parser.set_defaults(func=setup)
    # parser for 'manifest' action
    manifest_parser = actionparser.add_parser("manifest", help=manifest_help)
    manifest_parser.add_argument("-s", "--src-dir", default="sources", help=source_dir_help)
    manifest_parser.add_argument("-t", "--top-dir", default=os.getcwd(), help=top_dir_help)
    manifest_parser.add_argument("-a", "--archive", default="archive.tar.bz2", help=archive_file_help)
    manifest_parser.set_defaults(func=manifest)
    # parser for 'json-refresh' action
    jsongen_parser = actionparser.add_parser("json-gen", help=json_gen_help)
    jsongen_parser.add_argument("-s", "--src-dir", default="sources", help=source_dir_help)
    jsongen_parser.add_argument("-t", "--top-dir", default=os.getcwd(), help=top_dir_help)
    jsongen_parser.add_argument("-j", "--json-out", default="LAYERS.json", help=json_out_help)
    jsongen_parser.set_defaults(func=json_gen)
    # generate LAYERS file from current state
    layersgen_parser = actionparser.add_parser("layers-gen", help=layers_gen_help)
    layersgen_parser.add_argument("-s", "--src-dir", default="sources", help=source_dir_help)
    layersgen_parser.add_argument("-t", "--top-dir", default=os.getcwd(), help=top_dir_help)
    layersgen_parser.add_argument("-l", "--layers-file", default="LAYERS", help=layers_file_help)
    layersgen_parser.add_argument("-b", "--bblayers-file", default="conf/bblayers.conf", help=bblayers_help)
    layersgen_parser.set_defaults(func=layers_gen)
    # Fetch repos and set their state to match the specification in the JSON
    # file
    fetch_help = "Fetch repos and set them to the state defined in JSON file."
    fetch_update_help = "Update existing repos if necessary. Use carefully."
    fetch_parser = actionparser.add_parser("fetch", help=fetch_help)
    fetch_parser.add_argument("-s", "--src-dir", default="sources", help=source_dir_help)
    fetch_parser.add_argument("-t", "--top-dir", default=os.getcwd(), help=top_dir_help)
    fetch_parser.add_argument("-j", "--json-in", default="LAYERS.json", help=repos_json_help)
    fetch_parser.add_argument("-u", "--update", action="store_true", default=False, help=fetch_update_help)
    fetch_parser.set_defaults(func=fetch_repos)

    args = parser.parse_args()
    args.func(args)

    return 

if __name__ == '__main__':
    main()

