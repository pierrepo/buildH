#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""
Module for geometric operations
"""


import numpy as np


def normalize(vec):
    """Normalizes a vector.

    Parameters
    ----------
    vec : numpy 1D-array

    Returns
    -------
    numpy 1D-array
        The normalized vector.
    """
    return vec / norm(vec)


def norm(vec):
    """Returns the norm of a vector.

    Parameters
    ----------
    vec : numpy 1D-array

    Returns
    -------
    float
        The magniture of the vector.
    """
    return np.sqrt(np.sum(vec**2))


def calc_angle(atom1, atom2, atom3):
    """Calculates the valence angle between atom1, atom2 and atom3.

    Note: atom2 is the central atom.

    Parameters
    ----------
    atom1 : numpy 1D-array.
    atom2 : numpy 1D-array.
    atom3 : numpy 1D-array.

    Returns
    -------
    float
        The calculated angle in radians.
    """
    vec1 = atom1 - atom2
    vec2 = atom3 - atom2
    costheta = np.dot(vec1, vec2)/(norm(vec1)*norm(vec2))
    if costheta > 1.0 or costheta < -1.0:
        raise ValueError("Cosine cannot be larger than 1.0 or less than -1.0")
    return np.arccos(costheta)


def vec2quaternion(vec, theta):
    """Translates a vector of 3 elements and angle theta to a quaternion.

    Parameters
    ----------
    vec : numpy 1D-array
        Vector of the quaternion.
    theta : float
        Angle of the quaternion in radian.

    Returns
    -------
    numpy 1D-array
        The full quaternion (4 elements).
    """
    w = np.cos(theta/2)
    x, y, z = np.sin(theta/2) * normalize(vec)
    q = np.array([w, x, y, z])
    return q


def calc_rotation_matrix(quaternion):
    """Translates a quaternion to a rotation matrix.

    Parameters
    ----------
    quaternion : numpy 1D-array of 4 elements.

    Returns
    -------
    numpy 2D-array (dimension [3, 3])
        The rotation matrix.
    """
    # Initialize rotation matrix.
    matrix = np.zeros([3, 3])
    # Get quaternion elements.
    w, x, y, z = quaternion
    # Compute rotation matrix.
    matrix[0, 0] = w**2 + x**2 - y**2 - z**2
    matrix[1, 0] = 2 * (x*y + w*z)
    matrix[2, 0] = 2 * (x*z - w*y)
    matrix[0, 1] = 2 * (x*y - w*z)
    matrix[1, 1] = w**2 - x**2 + y**2 - z**2
    matrix[2, 1] = 2 * (y*z + w*x)
    matrix[0, 2] = 2 * (x*z + w*y)
    matrix[1, 2] = 2 * (y*z - w*x)
    matrix[2, 2] = w**2 - x**2 - y**2 + z**2
    return matrix


def apply_rotation(vec_to_rotate, rotation_axis, rad_angle):
    """Rotates a vector around an axis by a given angle.

    Note: the rotation axis is a vector of 3 elements.

    Parameters
    ----------
    vec_to_rotate : numpy 1D-array
    rotation_axis : numpy 1D-array
    rad_angle : float

    Returns
    -------
    numpy 1D-array
        The final rotated (normalized) vector.
    """
    # Generate a quaternion of the given angle (in radian).
    quaternion = vec2quaternion(rotation_axis, rad_angle)
    # Generate the rotation matrix.
    rotation_matrix = calc_rotation_matrix(quaternion)
    # Apply the rotation matrix on the vector to rotate.
    vec_rotated = np.dot(rotation_matrix, vec_to_rotate)
    return normalize(vec_rotated)


def cross_product(A, B):
    """Returns the cross product between vectors A & B.

    Source: http://hyperphysics.phy-astr.gsu.edu/hbase/vvec.html.
    Note: on small vectors (i.e. of 3 elements), computing cross products
          with this functions is faster than np.cross().

    Parameters
    ----------
    A : numpy 1D-array
        A vector of 3 elements.
    B : numpy 1D-array
        Another vector of 3 elements.

    Returns
    -------
    numpy 1D-array
        Cross product of A^B.
    """
    x = (A[1]*B[2]) - (A[2]*B[1])
    y = (A[0]*B[2]) - (A[2]*B[0])
    z = (A[0]*B[1]) - (A[1]*B[0])
    return np.array((x, -y, z))
