#!/usr/bin/env python

################################################################################
# Copyright (C) 2014, 2015 GenAP, McGill University and Genome Quebec Innovation Centre
#
# This file is part of MUGQIC Pipelines.
#
# MUGQIC Pipelines is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MUGQIC Pipelines is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with MUGQIC Pipelines.  If not, see <http://www.gnu.org/licenses/>.
################################################################################

# Python Standard Modules
import os

# MUGQIC Modules
from core.config import *
from core.job import *

def align(input1, input2, output_directory, outfile):

    inputs = []
    inputs.append(input1)
    if input2: 
        inputs.append(input2)

    return Job(
        inputs,
        [outfile],
        [
            ['bismark_align', 'module_bismark'],
            ['bismark_align', 'module_bowtie'],
            ['bismark_align', 'module_samtools']
        ],
        command="""\
bismark -q \\
  {other_options} \\
  {genome_directory} \\
  {input1} \\
  {input2} \\
  --output_dir {output_directory}""".format(
            other_options=config.param('bismark_align', 'other_options'),
            genome_directory=config.param('bismark_align', 'assembly_dir'),
            input1="-1 "+input1,
            input2="-2 "+input2 if input2 else "",
            output_directory=output_directory,
        )
    )

def dedup(input, output, library_type="PAIRED_END"):

    return Job(
        [input],
        [output],
        [
            ['bismark_dedup', 'module_bismark'],
            ['bismark_dedup', 'module_bowtie'],
            ['bismark_dedup', 'module_samtools']

        ],
        command="""\
deduplicate_bismark \\
  {library} \\
  {other_options} \\
  {input}""".format(
        other_options=config.param('bismark_dedup', 'other_options'),
        library="-p" if library_type=="PAIRED_END" else "-s",
        input=input
        ),
        removable_files=[re.sub(".bam", ".deduplicated.bam", input)]
    )

def methyl_call(input, outputs, library_type="PAIRED_END"):

    return Job(
        [input],
        outputs,
        [
            ['bismark_methyl_call', 'module_bismark'],
            ['bismark_methyl_call', 'module_samtools']

        ],
        command="""\
bismark_methylation_extractor \\
  {library} \\
  {other_options} \\
  --output {output_directory} \\
  {input}""".format(
        other_options=config.param('bismark_methyl_call', 'other_options'),
        library="-p" if library_type=="PAIRED_END" else "-s",
        input=input,
        output_directory=os.path.dirname(input)
        ),
        removable_files=[re.sub(".bam", ".deduplicated.bam", input)]
    )

def bed_graph(inputs, output, output_directory):

    return Job(
        inputs,
        [output],
        [
            ['bismark_bed_graph', 'module_bismark']
        ],
        command="""\
bismark2bedGraph \\
  {other_options} \\
  --output {output} \\
  --dir {directory} \\
  {inputs}""".format(
            inputs="".join([" \\\n  " + input for input in inputs]),
            output=os.path.join(output_directory, output),
            directory=output_directory,
            other_options=config.param('bismark_bed_graph', 'other_options')
        )
    )

def coverage2cytosine(input, output, output_directory):
    return Job(
        inputs,
        [output],
        [
            ['bismark_coverage2cytosine', 'module_bismark']
        ],
        command="""\
coverage2cytosine \\
  {other_options} \\
  --dir {directory} \\
  --output {output} \\
  {input}""".format(
            input=input,
            output=os.path.join(output_directory, output),
            directory=output_directory,
            other_options=config.param('bismark_coverage2cytosine', 'other_options')
        )
    )