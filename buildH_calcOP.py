#!/usr/bin/env python3
# coding: utf-8

"""
This script builds hydrogens from a united-atom trajectory and calculate the
order parameter for each C-H bond.

It works in two modes :
  1) A slow mode when an output trajectory (e.g. in xtc format) is requested by
     the user. In this case, the whole trajectory including newly built
     hydrogens are written to this trajectory.
  2) A fast mode without any output trajectory.
For both modes, the order parameter is written to an output file in a format
similar to the code of @jmelcr:
https://github.com/NMRLipids/MATCH/blob/master/scripts/calcOrderParameters.py

This code has been checked against the one from @jmelcr. You might find minor
differences due to rounding errors (in xtc, only 3 digits are written).

The way of building H is largely inspired from a code of Jon Kapla originally
written in fortran :
https://github.com/kaplajon/trajman/blob/master/module_trajop.f90#L242.

Note: that all coordinates in this script are handled using numpy 1D-arrays
of 3 elements, e.g. atom_coor = np.array((x, y, z)).
Note2: sometimes numpy is slow on small arrays, thus we wrote a few "in-house"
functions for vectorial operations (e.g. cross product).
"""

__authors__ = ("Patrick Fuchs", "Amélie Bâcle", "Hubert Santuz",
               "Pierre Poulain")
__contact__ = ("patrickfuchs", "abacle", "hublot", "pierrepo") # on github
__version__ = "1.0.3"
__copyright__ = "BSD"
__date__ = "2019/05"

# Modules.
import argparse
import collections
import pickle
import sys
import warnings
import pathlib

import numpy as np
import MDAnalysis as mda
import MDAnalysis.coordinates.XTC as XTC

import dic_lipids
import OP


# For debugging.
DEBUG = False
# For pickling results (useful for future analyses, e.g. drawing distributions).
PICKLE = False

def isfile(path):
    """Callback for checking file existence.

    This function checks if path is an existing file.
    If not, raise an error. Else, return the path.

    Parameters
    ----------
    path : str
        The path to be checked.

    Returns
    -------
    str
        The validated path.
"""
    source = pathlib.Path(path)
    if not pathlib.Path.is_file(source):
        if pathlib.Path.is_dir(source):
            msg = f"{source} is a directory"
        else:
            msg = f"{source} does not exist."
        raise argparse.ArgumentTypeError(msg)
    return path







def pandasdf2pdb(df):
    """Returns a string in PDB format from a pandas dataframe.

    Parameters
    ----------
    df : pandas dataframe with columns "atnum", "atname", "resname", "resnum",
         "x", "y", "z"

    Returns
    -------
    str
        A string representing the PDB.
    """
    s = ""
    chain = ""
    for _, row_atom in df.iterrows():
        atnum, atname, resname, resnum, x, y, z = row_atom
        atnum = int(atnum)
        resnum = int(resnum)
        # See for pdb format:
        # https://www.cgl.ucsf.edu/chimera/docs/UsersGuide/tutorials/pdbintro.html.
        # "alt" means alternate location indicator
        # "code" means code for insertions of residues
    	# "seg" means segment identifier
        # "elt" means element symbol
        if len(atname) == 4:
            s += ("{record_type:6s}{atnum:5d} {atname:<4s}{alt:1s}{resname:>4s}"
                  "{chain:1s}{resnum:>4d}{code:1s}   {x:>8.3f}{y:>8.3f}{z:>8.3f}"
                  "{occupancy:>6.2f}{temp_fact:>6.2f}          {seg:<2s}{elt:>2s}\n"
                  .format(record_type="ATOM", atnum=atnum, atname=atname, alt="",
                          resname=resname, chain=chain, resnum=resnum, code="",
                          x=x, y=y, z=z, occupancy=1.0, temp_fact=0.0, seg="",
                          elt=atname[0]))
        else:
            s += ("{record_type:6s}{atnum:5d}  {atname:<3s}{alt:1s}{resname:>4s}"
                  "{chain:1s}{resnum:>4d}{code:1s}   {x:>8.3f}{y:>8.3f}{z:>8.3f}"
                  "{occupancy:>6.2f}{temp_fact:>6.2f}          {seg:<2s}{elt:>2s}\n"
                  .format(record_type="ATOM", atnum=atnum, atname=atname, alt="",
                          resname=resname, chain=chain, resnum=resnum, code="",
                          x=x, y=y, z=z, occupancy=1.0, temp_fact=0.0, seg="",
                          elt=atname[0]))
    return s


def make_dic_atname2genericname(filename):
    """Make a dict of correspondance between generic H names and PDB names.

    This dict will look like the following: {('C1', 'H11'): 'gamma1_1', ...}.
    Useful for outputing OP with generic names (such as beta1, beta 2, etc.).
    Such files can be found on the NMRlipids MATCH repository:
    https://github.com/NMRLipids/MATCH/tree/master/scripts/orderParm_defs.

    Parameters
    ----------
    filename : str
        Filename containing OP definition
        (e.g. `order_parameter_definitions_MODEL_Berger_POPC.def`).

    Returns
    -------
    Ordered dictionnary
        Keys are tuples of (C, H) name, values generic name (as described
        above in this docstring). The use of an ordered dictionnary ensures
        we get always the same order in the output OP.
    """
    dic = collections.OrderedDict()
    try:
        with open(filename, "r") as f:
            for line in f:
                # TODO: This line might have to be changed if the file contains more than
                # 4 columns.
                name, _, C, H = line.split()
                dic[(C, H)] = name
    except:
        raise UserWarning("Can't read order parameter definition in "
                          "file {}".format(filename))
    return dic

def init_dic_OP(universe_woH, dic_atname2genericname):
    """TODO Complete docstring.
    """
    ### To calculate the error, we need to first average over the
    ### trajectory, then over residues.
    ### Thus in dic_OP, we want for each key a list of lists, for example:
    ### OrderedDict([
    ###              (('C1', 'H11'), [[], [], ..., [], []]),
    ###              (('C1', 'H12'), [[], ..., []]),
    ###              ...
    ###              ])
    ### Thus each sublist will contain OPs for one residue.
    ### e.g. ('C1', 'H11'), [[OP res 1 frame1, OP res1 frame2, ...],
    ###                      [OP res 2 frame1, OP res2 frame2, ...], ...]
    dic_OP = collections.OrderedDict()
    # We also need the correspondance between residue number (resnum) and
    # its index in dic_OP.
    dic_corresp_numres_index_dic_OP = {}
    # Create these sublists by looping over each lipid.
    for key in dic_atname2genericname:
        dic_OP[key] = []
        # Get lipid name.
        resname = dic_lipid["resname"]
        selection = "resname {}".format(resname)
        # Loop over each residue on which we want to calculate the OP on.
        for i, residue in enumerate(universe_woH.select_atoms(selection).residues):
            dic_OP[key].append([])
            dic_corresp_numres_index_dic_OP[residue.resid] = i
    if DEBUG:
        print("Initial dic_OP:", dic_OP)
        print("dic_corresp_numres_index_dic_OP:", dic_corresp_numres_index_dic_OP)
    return dic_OP, dic_corresp_numres_index_dic_OP


def make_dic_Cname2Hnames(dic_OP):
    """TODO Complete Docstring.
    """
    dic = {}
    for Cname, Hname in dic_OP.keys():
        if Cname not in dic:
            dic[Cname] = (Hname,)
        else:
            dic[Cname] += (Hname,)
    if DEBUG:
        print("dic_Cname2Hnames contains:", dic)
    return dic


def check_slice_options(system, first_frame=None, last_frame=None):
    """Verify the slicing options given by the user and translate
    to it to a range of frame in MDAnalysis.

    This function check whether the first frame and the last frame are consistent
    within themselves (``first_frame`` cant be superior to ``last_frame``) and
    with the trajectory supplied (if the trajectory starts at 1000ps, ``first_frame``
    cant be equal to 0 for example).
    Then, the function translate the range from picosecond-time to the number of frame
    in MDanalysis.


    Parameters
    ----------
    system : MDAnalysis universe instance
        This is the universe *without* hydrogen.
    first_frame : int
        the first frame to read (in ps)
    last_frame : int
        the last frame to read (in ps)

    Return
    ------
    tuple of int
        The number of first and last frame

    Raises
    ------
    """
    # From the trajectory, get the time of the first and last frame
    traj_first_frame = int(universe_woH.trajectory.time)
    traj_last_frame = int(universe_woH.trajectory.time + universe_woH.trajectory.dt * (universe_woH.trajectory.n_frames - 1))

    # If no bound is given, take the full trajectory
    if not first_frame and not last_frame:
        return (0, universe_woH.trajectory.n_frames)

    # If only one bound is given
    if not first_frame:
        first_frame = traj_first_frame
    if not last_frame:
        last_frame = traj_last_frame


    # Check abnormal range
    if first_frame < 0 or last_frame < 0:
        raise IndexError("Incorrect slice options.")
    if first_frame > last_frame:
        raise  IndexError("Incorrect slice options")

    # Check if the range fits into the range of the trajectory
    if first_frame < traj_first_frame or last_frame < traj_first_frame:
        raise  IndexError("Incorrect slice options")
    if first_frame > traj_last_frame or last_frame > traj_last_frame:
        raise  IndexError("Incorrect slice options")

    # Translate the time range into a number range.
    # Find the index of element in the list of frames (in ps) which has the minimum distance
    # from the first or last frame (in ps) given.
    frames = np.arange(traj_first_frame, traj_last_frame + 1, int(universe_woH.trajectory.dt))
    number_first_frame = (np.abs(frames - first_frame)).argmin()
    number_last_frame  = (np.abs(frames -  last_frame)).argmin()
    # Include last frame into account for slicing by adding 1
    number_last_frame = number_last_frame + 1

    return (number_first_frame, number_last_frame)

if __name__ == "__main__":
    # 0) Fist ensure Python 3 is used!!!
    major, minor, _, _, _ = sys.version_info
    if major != 3:
        raise UserWarning("buildH only works with Python 3.")
    if minor < 6:
        warnings.warn("Python version >= 3.6 is recommended with buildH.", UserWarning)
    else:
        print("Python version OK!")

    # 1) Parse arguments.
    # TODO --> Make a function for that.
    message = """This program builds hydrogens and calculate the order
    parameters
    (OP) from a united-atom trajectory. If -opx is requested, pdb and xtc
    output files with hydrogens are created but OP calculation will be slow.
    If no trajectory output is requested (no use of flag -opx), it uses a
    fast procedure to build hydrogens and calculate the OP.
    """
    parser = argparse.ArgumentParser(description=message)
    # Avoid tpr for topology cause there's no .coord there!
    parser.add_argument("topfile", type=isfile,
                        help="Topology file (pdb or gro).")
    parser.add_argument("-x", "--xtc", type=isfile,
                        help="Input trajectory file in xtc format.")
    parser.add_argument("-l", "--lipid", type=str, required=True,
                        help="Residue name of lipid to calculate the OP on (e.g. POPC).")
    parser.add_argument("-d", "--defop", required=True, type=isfile,
                        help="Order parameter definition file. Can be found on "
                        "NMRlipids MATCH repository:"
                        "https://github.com/NMRLipids/MATCH/tree/master/scripts/orderParm_defs")
    parser.add_argument("-opx", "--opdbxtc", help="Base name for trajectory "
                        "output with hydrogens. File extension will be "
                        "automatically added. For example -opx trajH will "
                        "generate trajH.pdb and trajH.xtc. "
                        "So far only xtc is supported.")
    parser.add_argument("-o", "--out", help="Output base name for storing "
                        "order parameters. Extention \".out\" will be "
                        "automatically added. Default name is OP_buildH.out.",
                        default="OP_buildH.out")
    parser.add_argument("-b", "--begin", type=int,
                        help="The first frame (ps) to read from the trajectory.")
    parser.add_argument("-e", "--end", type=int,
                        help="The last frame (ps) to read from the trajectory.")
    args = parser.parse_args()

    # Top file is "args.topfile", xtc file is "args.xtc", pdb output file is
    # "args.pdbout", xtc output file is "args.xtcout".
    # Check topology file extension.
    if not args.topfile.endswith("pdb") and not args.topfile.endswith("gro"):
        parser.error("Topology must be given in pdb or gro format")
    # Check residue name validity.
    # Get the dictionnary with helper info using residue name (args.lipid
    # argument). Beware, this dict is then called `dic_lipid` *without s*,
    # while `dic_lipids.py` (with an s) is a module with many different dicts
    # (of different lipids) the user can choose.
    try:
        dic_lipid = getattr(dic_lipids, args.lipid)
    except:
        parser.error("Lipid dictionnary {} doesn't exist in dic_lipids.py".format(args.lipid))

    # Slicing only makes sense with a trajectory
    if not args.xtc and (args.begin or args.end):
        parser.error("Slicing is only possible with a trajectory file.")

    # 2) Create universe without H.
    print("Constructing the system...")
    if args.xtc:
        try:
            universe_woH = mda.Universe(args.topfile, args.xtc)
            begin, end = check_slice_options(universe_woH, args.begin, args.end)
        except IndexError:
            raise UserWarning("Slicing options are not correct.") from None
        except:
            raise UserWarning("Can't create MDAnalysis universe with files {} "
                              "and {}".format(args.topfile, args.xtc)) from None
    else:
        try:
            universe_woH = mda.Universe(args.topfile)
            begin = 0
            end = 1
        except:
            raise UserWarning("Can't create MDAnalysis universe with file {}"
                              .format(args.topfile))
    print("System has {} atoms".format(len(universe_woH.coord)))

    # 2) Initialize dic for storing OP.
    # Init dic of correspondance : {('C1', 'H11'): 'gamma1_1',
    # {('C1', 'H11'): 'gamma1_1', ...}.
    dic_atname2genericname = make_dic_atname2genericname(args.defop)
    # Initialize dic_OP (see function init_dic_OP() for the format).
    dic_OP, dic_corresp_numres_index_dic_OP = init_dic_OP(universe_woH,
                                                          dic_atname2genericname)
    # Initialize dic_Cname2Hnames.
    dic_Cname2Hnames = make_dic_Cname2Hnames(dic_OP)

    # If traj output files are requested.
    # NOTE Here, we need to reconstruct all Hs. Thus the op definition file (passed
    #  with arg -d) needs to contain all possible C-H pairs !!!
    if args.opdbxtc:
        #3) Prepare the system.
        # First check that dic_OP contains all possible C-H pairs.
        # NOTE The user has to take care that .def file has the right atom names !!!
        for atname in dic_lipid.keys():
            if atname != "resname":
                # Check if carbon is present in the definition file.
                if atname not in dic_Cname2Hnames:
                    print("Error: When -opx option is used, the order param "
                          "definition file (passed with -d arg) must contain "
                          "all possible carbons on which we want to rebuild "
                          "hydrogens.")
                    print("Found:", list(dic_Cname2Hnames.keys()))
                    print("Needs:", list(dic_lipid.keys()))
                    raise UserWarning("Order param definition file incomplete.")
                # Check that the 3 Hs are in there for that C.
                nbHs_in_def_file = len(dic_Cname2Hnames[atname])
                tmp_dic = {"CH": 1, "CHdoublebond": 1, "CH2": 2, "CH3": 3}
                correct_nb_of_Hs = tmp_dic[dic_lipid[atname][0]]
                if  correct_nb_of_Hs != nbHs_in_def_file:
                    print("Error: When -opx option is used, the order param "
                          "definition file (passed with -d arg) must contain "
                          "all possible C-H pairs to rebuild.")
                    print("Expected {} hydrogen(s) to rebuild for carbon {}, "
                          "got {} in definition file {}."
                          .format(correct_nb_of_Hs, atname,
                                  dic_Cname2Hnames[atname], args.defop))
                    raise UserWarning("Wrong number of Hs to rebuild.")
        # Create filenames.
        pdbout_filename = args.opdbxtc + ".pdb"
        xtcout_filename = args.opdbxtc + ".xtc"
        # Build a new universe with H.
        # Build a pandas df with H.
        new_df_atoms = OP.build_all_Hs_calc_OP(universe_woH, dic_lipid,
                                            dic_Cname2Hnames,
                                            return_coors=True)
        # Create a new universe with H using that df.
        print("Writing new pdb with hydrogens.")
        # Write pdb with H to disk.
        with open(pdbout_filename, "w") as f:
            f.write(pandasdf2pdb(new_df_atoms))
        # Then create the universe with H from that pdb.
        universe_wH = mda.Universe(pdbout_filename)
        # Create an xtc writer.
        print("Writing trajectory with hydrogens in xtc file.")
        newxtc = XTC.XTCWriter(xtcout_filename, len(universe_wH.atoms))
        # Write 1st frame.
        newxtc.write(universe_wH)

        # 4) Loop over all frames of the traj *without* H, build Hs and
        # calc OP (ts is a Timestep instance).
        for ts in universe_woH.trajectory[begin:end]:
            print("Dealing with frame {} at {} ps."
                  .format(ts.frame, universe_woH.trajectory.time))
            # Build H and update their positions in the universe *with* H (in place).
            # Calculate OPs on the fly while building Hs  (dic_OP changed in place).
            OP.build_all_Hs_calc_OP(universe_woH, dic_lipid, dic_Cname2Hnames,
                                    universe_wH=universe_wH, dic_OP=dic_OP,
                                    dic_corresp_numres_index_dic_OP=dic_corresp_numres_index_dic_OP)
            # Write new frame to xtc.
            newxtc.write(universe_wH)
        # Close xtc.
        newxtc.close()

    # 6) If no traj output file requested, use fast indexing to speed up OP
    # calculation. The function fast_build_all_Hs() returns nothing, dic_OP
    # is modified in place.
    if not args.opdbxtc:
        OP.fast_build_all_Hs_calc_OP(universe_woH, begin, end, dic_OP, dic_lipid, dic_Cname2Hnames)

    # 7) Output results.
    # Pickle results? (migth be useful in the future)
    # TODO Implement that option.
    if PICKLE:
        with open("OP.pickle", "wb") as f:
            # Pickle the dic using the highest protocol available.
            pickle.dump(dic_OP, f, pickle.HIGHEST_PROTOCOL)
        #  To unpickle
        #with open("OP.pickle", "rb") as f:
        #    dic_OP = pickle.load(f)
    # Output to a file.
    with open("{}.jmelcr_style.out".format(args.out), "w") as f, \
        open("{}.apineiro_style.out".format(args.out), "w") as f2:
        # J. Melcr output style.
        f.write("# {:18s} {:7s} {:5s} {:5s}  {:7s} {:7s} {:7s}\n"
                .format("OP_name", "resname", "atom1", "atom2", "OP_mean",
                        "OP_stddev", "OP_stem"))
        f.write("#-------------------------------"
                "-------------------------------------\n")
        # Loop over each pair (C, H).
        for Cname, Hname in dic_atname2genericname.keys():
            name = dic_atname2genericname[(Cname, Hname)]
            if DEBUG:
                print("Pair ({}, {}):".format(Cname, Hname))
            # Cast list of lists to a 2D-array. It should have dimensions
            # (nb_lipids, nb_frames).
            ### Thus each sublist will contain OPs for one residue.
            ### e.g. ('C1', 'H11'), [[OP res 1 frame1, OP res1 frame2, ...],
            ###                      [OP res 2 frame1, OP res2 frame2, ...],
            ####                     ...]
            a = np.array(dic_OP[(Cname, Hname)])
            if DEBUG:
                print("Final OP array has shape (nb_lipids, nb_frames):",
                      a.shape)
                print()
            # General mean over lipids and over frames (for that (C, H) pair).
            mean = np.mean(a)
            # Average over frames for each (C, H) pair.  Because of how the
            # array is organized (see above), we need to average horizontally
            # (i.e. using axis=1).
            # means is a 1D-array with nb_lipids elements.
            means = np.mean(a, axis=1)
            # Calc standard deviation and STEM (std error of the mean).
            std_dev = np.std(means)
            stem = np.std(means) / np.sqrt(len(means))
            f.write("{:20s} {:7s} {:5s} {:5s} {: 2.5f} {: 2.5f} {: 2.5f}\n"
                    .format(name, dic_lipid["resname"], Cname, Hname, mean,
                            std_dev, stem))
        # A. Pineiro output style.
        f2.write("Atom_name  Hydrogen\tOP\t      STD\t   STDmean\n")
        list_unique_Cnames = []
        for Cname, Hname in dic_OP.keys():
            if Cname not in list_unique_Cnames:
                list_unique_Cnames.append(Cname)
        # Order of carbons is similar to that in the PDB.
        list_unique_Cnames_ordered = []
        selection = "resname {}".format(dic_lipid["resname"])
        for atom in universe_woH.select_atoms(selection).residues[0].atoms:
            if atom.name in list_unique_Cnames:
                list_unique_Cnames_ordered.append(atom.name)
        # Now write output.
        for Cname in list_unique_Cnames_ordered:
            cumulative_list_for_that_carbon = []
            for i, Hname in enumerate([H for C, H in dic_OP.keys() if C == Cname]):
                cumulative_list_for_that_carbon += dic_OP[Cname, Hname]
                a = np.array(dic_OP[Cname, Hname])
                mean = np.mean(a)
                means = np.mean(a, axis=1)
                std_dev = np.std(means)
                stem = np.std(means) / np.sqrt(len(means))
                if i == 0:
                    f2.write("{:>7s}\t{:>8s}  {:10.5f}\t{:10.5f}\t{:10.5f}\n"
                             .format(Cname, "HR", mean, std_dev, stem))
                elif i == 1:
                    f2.write("{:>7s}\t{:>8s}  {:10.5f}\t{:10.5f}\t{:10.5f}\n"
                             .format("", "HS", mean, std_dev, stem))
                elif i == 2:
                    f2.write("{:>7s}\t{:>8s}  {:10.5f}\t{:10.5f}\t{:10.5f}\n"
                             .format("", "HT", mean, std_dev, stem))
            a = np.array(cumulative_list_for_that_carbon)
            mean = np.mean(a)
            means = np.mean(a, axis=1)
            std_dev = np.std(means)
            stem = np.std(means) / np.sqrt(len(means))
            f2.write("{:>7s}\t{:>8s}  {:10.5f}\t{:10.5f}\t{:10.5f}\n\n"
                     .format("", "AVG", mean, std_dev, stem))

    print("Results written to {}".format(args.out))
