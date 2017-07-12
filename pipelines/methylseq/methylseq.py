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
import logging
import math
import os
import re
import sys

# Append mugqic_pipelines directory to Python library path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))))

# MUGQIC Modules
from core.config import *
from core.job import *
from core.pipeline import *
from bfx.readset import *

from bfx import bvatools
from bfx import bismark
from bfx import picard2 as picard
from bfx import bedtools
from bfx import samtools
from bfx import gatk
from bfx import igvtools
from bfx import bissnp
from bfx import methyl_profile
from bfx import ucsc

from pipelines import common
from pipelines.dnaseq import dnaseq

log = logging.getLogger(__name__)

class MethylSeq(dnaseq.DnaSeq):
    """
    Methyl-Seq Pipeline
    ================

    The standard MUGQIC Methyl-Seq pipeline uses Bismark to align reads to the reference genome. Treatment
    and filtering of mapped reads approaches as mark duplicate reads, recalibration
    and sort are executed using Picard and GATK. Samtools MPILEUP and bcftools are used to produce
    the standard SNP and indels variants file (VCF). Additional SVN annotations mostly applicable
    to human samples include mappability flags, dbSNP annotation and extra information about SVN
    by using published databases.  The SNPeff tool is used to annotate variants using an integrated database
    of functional predictions from multiple algorithms (SIFT, Polyphen2, LRT and MutationTaster, PhyloP and GERP++, etc.)
    and to calculate the effects they produce on known genes.

    A summary html report is automatically generated by the pipeline. This report contains description
    of the sequencing experiment as well as a detailed presentation of the pipeline steps and results.
    Various Quality Control (QC) summary statistics are included in the report and additional QC analysis
    is accessible for download directly through the report. The report includes also the main references
    of the software and methods used during the analysis, together with the full list of parameters
    that have been passed to the pipeline main script.
    """

    #def __init__(self):
        #self.argparser.add_argument("-r", "--readsets", help="readset file", type=file)
        #super(MethylSeq, self).__init__()

    #@property
    #def readsets(self):
        #if not hasattr(self, "_readsets"):
            #if self.args.readsets:
                #self._readsets = parse_illumina_readset_file_for_methylseq(self.args.readsets.name)
            #else:
                #self.argparser.error("argument -r/--readsets is required!")

        #return self._readsets

    def bismark_align(self):
        """
        Align reads with Bismark
        """

        jobs = []
        for readset in self.readsets:
            trim_file_prefix = os.path.join("trim", readset.sample.name, readset.name + ".trim.")
            alignment_directory = os.path.join("alignment", readset.sample.name)
            readset_bam = os.path.join(alignment_directory, readset.name, readset.name + ".sorted_noRG.bam")

            # Find input readset FASTQs first from previous trimmomatic job, then from original FASTQs in the readset sheet
            if readset.run_type == "PAIRED_END":
                candidate_input_files = [[trim_file_prefix + "pair1.fastq.gz", trim_file_prefix + "pair2.fastq.gz"]]
                if readset.fastq1 and readset.fastq2:
                    candidate_input_files.append([readset.fastq1, readset.fastq2])
                if readset.bam:
                    candidate_input_files.append([re.sub("\.bam$", ".pair1.fastq.gz", readset.bam), re.sub("\.bam$", ".pair2.fastq.gz", readset.bam)])
                [fastq1, fastq2] = self.select_input_files(candidate_input_files)
            elif readset.run_type == "SINGLE_END":
                candidate_input_files = [[trim_file_prefix + "single.fastq.gz"]]
                if readset.fastq1:
                    candidate_input_files.append([readset.fastq1])
                if readset.bam:
                    candidate_input_files.append([re.sub("\.bam$", ".single.fastq.gz", readset.bam)])
                [fastq1] = self.select_input_files(candidate_input_files)
                fastq2 = None
            else:
                raise Exception("Error: run type \"" + readset.run_type +
                "\" is invalid for readset \"" + readset.name + "\" (should be PAIRED_END or SINGLE_END)!")

            # Defining the bismark output files (bismark sets the names of its output files from the basename of fastq1)
            # Note : these files will then be renamed (using a "mv" command) to fit with a more broad nomenclature (cf. readset_bam)
            bismark_out_bam = os.path.join(alignment_directory, readset.name, re.sub(r'(\.fastq\.gz|\.fq\.gz|\.fastq|\.fq)$', "_bismark_bt2_pe.bam", os.path.basename(fastq1)))
            bismark_out_report =  os.path.join(alignment_directory, readset.name, re.sub(r'(\.fastq\.gz|\.fq\.gz|\.fastq|\.fq)$', "_bismark_bt2_PE_report.txt", os.path.basename(fastq1)))

            jobs.append(
                concat_jobs([
                    Job(output_files=[readset_bam], command="mkdir -p " + os.path.dirname(readset_bam)),
                    bismark.align(
                        fastq1,
                        fastq2,
                        os.path.dirname(readset_bam),
                        re.sub(".bam", "", os.path.basename(readset_bam)),
                    ),
                    Job(command="mv " + bismark_out_bam + " " + readset_bam),
                    Job(command="mv " + bismark_out_report + " " + re.sub(".bam", "_bismark_bt2_PE_report.txt", readset_bam))
                ], name="bismark_align." + readset.name)
            )

        return jobs

    def picard_add_read_groups(self):
        """
        Add reads groups to our bam files since Bismark align did not do it previously, useful when merging differnent lanes for one sample
        """

        jobs = []
        for readset in self.readsets:
            alignment_directory = os.path.join("alignment", readset.sample.name)

            candidate_input_files = [[os.path.join(alignment_directory, readset.name, readset.name + ".sorted_noRG.bam")]]
            if readset.bam:
                candidate_input_files.append([readset.bam])
            [input_bam] = self.select_input_files(candidate_input_files)
            output_bam = re.sub("_noRG.bam", ".bam", input_bam)

            jobs.append(
                concat_jobs([
                    Job(command="mkdir -p " + alignment_directory),
                    picard.add_read_groups(
                        input_bam,
                        output_bam,
                        readset.name,
                        readset.library,
                        readset.lane,
                        readset.sample.name
                    )
                ], name="picard_add_read_groups." + readset.name)
            )

        return jobs

    def bismark_dedup(self):
        """
        Remove duplicates reads with Bismark
        """

        # Check the library status
        library = {}
        for readset in self.readsets:
            if not library.has_key(readset.sample) :
                library[readset.sample]="SINGLE_END"
            if readset.run_type == "PAIRED_END" :
                library[readset.sample]="PAIRED_END"

        jobs = []
        for sample in self.samples:
            alignment_directory = os.path.join("alignment", sample.name)
            bam_input = os.path.join(alignment_directory, sample.name + ".sorted.bam")
            bam_readset_sorted = re.sub(".sorted.bam", ".readset_sorted.bam", bam_input)
            dedup_bam_readset_sorted = re.sub(".bam", ".dedup.bam", bam_readset_sorted)
            bam_output = re.sub("readset_", "", dedup_bam_readset_sorted)

            job = concat_jobs([
                Job(command="mkdir -p " + alignment_directory),
                picard.sort_sam(
                    bam_input,
                    bam_readset_sorted,
                    "queryname"
                ),
                bismark.dedup(
                    bam_readset_sorted,
                    dedup_bam_readset_sorted,
                    library[sample]
                ),
                Job(command="mv " + re.sub(".bam", ".deduplicated.bam", bam_readset_sorted) + " " + dedup_bam_readset_sorted),
                picard.sort_sam(
                    dedup_bam_readset_sorted,
                    bam_output
                )
            ])
            job.name = "bismark_dedup." + sample.name
            job.removable_files = [dedup_bam_readset_sorted]

            jobs.append(job)

        return jobs

    def metrics(self):
        """
        Compute metrics and generate coverage tracks per sample. Multiple metrics are computed at this stage:
        Number of raw reads, Number of filtered reads, Number of aligned reads, Number of duplicate reads,
        Median, mean and standard deviation of insert sizes of reads after alignment, percentage of bases
        covered at X reads (%_bases_above_50 means the % of exons bases which have at least 50 reads)
        whole genome or targeted percentage of bases covered at X reads (%_bases_above_50 means the % of exons
        bases which have at least 50 reads). A TDF (.tdf) coverage track is also generated at this step
        for easy visualization of coverage in the IGV browser.
        """

        ##check the library status
        library, bam = {}, {}
        for readset in self.readsets:
            if not library.has_key(readset.sample) :
                library[readset.sample]="SINGLE_END"
            if readset.run_type == "PAIRED_END" :
                library[readset.sample]="PAIRED_END"
            if not bam.has_key(readset.sample):
                bam[readset.sample]=""
            if readset.bam:
                bam[readset.sample]=readset.bam

        jobs = []
        created_interval_lists = []
        for sample in self.samples:
            file_prefix = os.path.join("alignment", sample.name, sample.name + ".sorted.dedup.")
            coverage_bed = bvatools.resolve_readset_coverage_bed(sample.readsets[0])

            candidate_input_files = [[file_prefix + "bam"]]
            if bam[sample]:
                candidate_input_files.append([bam[sample]])
            [input] = self.select_input_files(candidate_input_files)

            job = picard.collect_multiple_metrics(
                input,
                re.sub("bam", "all.metrics", input),
                library_type=library[sample]
            )
            job.name = "picard_collect_multiple_metrics." + sample.name
            jobs.append(job)

            # Compute genome coverage with GATK
            job = gatk.depth_of_coverage(
                input,
                re.sub("bam", "all.coverage", input),
                coverage_bed
            )
            job.name = "gatk_depth_of_coverage.genome." + sample.name
            jobs.append(job)

            # Compute genome or target coverage with BVATools
            job = bvatools.depth_of_coverage(
                input,
                re.sub("bam", "coverage.tsv", input),
                coverage_bed,
                other_options=config.param('bvatools_depth_of_coverage', 'other_options', required=False)
            )
            job.name = "bvatools_depth_of_coverage." + sample.name
            jobs.append(job)

            if coverage_bed:
                # Get on-target reads (if on-target context is detected)
                ontarget_bam = re.sub("bam", "ontarget.bam", input)
                flagstat_output = re.sub("bam", "bam.flagstat", input)
                job = concat_jobs([
                    bedtools.intersect(
                        input,
                        ontarget_bam,
                        coverage_bed
                    ),
                    samtools.flagstat(
                        ontarget_bam,
                        flagstat_output
                    )
                ])
                job.name = "ontarget_reads." + sample.name
                job.removable_files=[ontarget_bam]
                jobs.append(job)

                # Compute on target percent of hybridisation based capture
                interval_list = re.sub("\.[^.]+$", ".interval_list", coverage_bed)
                if not interval_list in created_interval_lists:
                    job = tools.bed2interval_list(None, coverage_bed, interval_list)
                    job.name = "interval_list." + os.path.basename(coverage_bed)
                    jobs.append(job)
                    created_interval_lists.append(interval_list)
                file_prefix = os.path.join("alignment", sample.name, sample.name + ".sorted.dedup.")
                job = picard.calculate_hs_metrics(file_prefix + "bam", file_prefix + "onTarget.tsv", interval_list)
                job.name = "picard_calculate_hs_metrics." + sample.name
                jobs.append(job)

            # Calculate the number of reads with higher mapping quality than the threshold passed in the ini file
            job = concat_jobs([
                samtools.view(
                    input,
                    re.sub(".bam", ".filtered_reads.counts.txt", input),
                    "-c " + config.param('mapping_quality_filter', 'quality_threshold')
                )
            ])
            job.name = "mapping_quality_filter." + sample.name
            jobs.append(job)

            # Calculate GC bias
            job = concat_jobs([
                pipe_jobs([
                    bedtools.bamtobed(
                        input,
                        None
                    ),
                    bedtools.coverage(
                        None,
                        re.sub(".bam", ".gc_cov.1M.txt", input)
                    )
                ]),
                metrics.gc_bias(
                    re.sub(".bam", ".gc_cov.1M.txt", input),
                    re.sub(".bam", ".GCBias_all.txt", input)
                )
            ])
            job.name = "GC_bias." + sample.name
            jobs.append(job)

            job = igvtools.compute_tdf(input, input + ".tdf")
            job.name = "igvtools_compute_tdf." + sample.name
            jobs.append(job)

        return jobs

    def methylation_call(self):
        """
        The script reads in a bisulfite read alignment file produced by the Bismark bisulfite mapper
        and extracts the methylation information for individual cytosines.
        The methylation extractor outputs result files for cytosines in CpG, CHG and CHH context.
        It also outputs bedGraph, a coverage file from positional methylation data and cytosine methylation report
        """

        # Check the library status
        library = {}
        for readset in self.readsets:
            if not library.has_key(readset.sample) :
                library[readset.sample]="SINGLE_END"
            if readset.run_type == "PAIRED_END" :
                library[readset.sample]="PAIRED_END"

        jobs = []
        for sample in self.samples:
            alignment_directory = os.path.join("alignment", sample.name)

            candidate_input_files = [[os.path.join(alignment_directory, sample.name + ".readset_sorted.dedup.bam")]]
            candidate_input_files.append([os.path.join(alignment_directory, sample.name + ".sorted.dedup.bam")])
            candidate_input_files.append([os.path.join(alignment_directory, sample.name + ".sorted.bam")])
            [input_file] = self.select_input_files(candidate_input_files)

            methyl_directory = os.path.join("methylation_call", sample.name)
            outputs = [
                os.path.join(methyl_directory, "CpG_context_" + re.sub( ".bam", ".txt.gz", os.path.basename(input_file))),
                os.path.join(methyl_directory, re.sub(".bam", ".bedGraph.gz", os.path.basename(input_file))),
                os.path.join(methyl_directory, re.sub(".bam", ".CpG_report.txt.gz", os.path.basename(input_file)))
            ]

            if input_file == os.path.join(alignment_directory, sample.name + ".readset_sorted.dedup.bam") :
                bismark_job = bismark.methyl_call(
                    input_file,
                    outputs,
                    library[sample]
                )
            else :
                outputs = [re.sub("sorted", "readset_sorted", output) for output in outputs]
                bismark_job = concat_jobs([
                    picard.sort_sam(
                        input_file,
                        re.sub("sorted", "readset_sorted", input_file),
                        "queryname"
                    ),
                    bismark.methyl_call(
                        re.sub("sorted", "readset_sorted", input_file),
                        outputs,
                        library[sample]
                    )
                ])

            jobs.append(
                concat_jobs([
                    Job(command="mkdir -p " + methyl_directory),
                    bismark_job,
                ], name="bismark_methyl_call." + sample.name)
            )

        return jobs

    def wiggle_tracks(self):
        """
        Generate wiggle tracks suitable for multiple browsers, to show coverage and methylation data
        """

        jobs = []

        for sample in self.samples:
            alignment_directory = os.path.join("alignment", sample.name)

            # Generation of a bedGraph and a bigWig track to show the genome coverage
            candidate_input_files = [[os.path.join(alignment_directory, sample.name + ".sorted.dedup.bam")]]
            candidate_input_files.append([os.path.join(alignment_directory, sample.name + ".readset_sorted.dedup.bam")])

            [input_bam] = self.select_input_files(candidate_input_files)

            bed_graph_prefix = os.path.join("tracks", sample.name, sample.name)
            big_wig_prefix = os.path.join("tracks", "bigWig", sample.name)

            bed_graph_output = bed_graph_prefix + ".bedGraph"
            big_wig_output = big_wig_prefix + ".bw"

            if input_bam == os.path.join(alignment_directory, sample.name + ".readset_sorted.dedup.bam") :
                jobs.append(
                    concat_jobs([
                        Job(command="mkdir -p " + os.path.join("tracks", sample.name) + " " + os.path.join("tracks", "bigWig"), removable_files=["tracks"]),
                        picard.sort_sam(
                            input_bam,
                            re.sub("readset_sorted", "sorted", input_bam),
                            "coordinate"
                        ),
                        bedtools.graph(re.sub("readset_sorted", "sorted", input_bam), bed_graph_output, big_wig_output, "")
                    ], name="wiggle." + re.sub(".bedGraph", "", os.path.basename(bed_graph_output)))
                )
            else :
                jobs.append(
                    concat_jobs([
                        Job(command="mkdir -p " + os.path.join("tracks", sample.name) + " " + os.path.join("tracks", "bigWig"), removable_files=["tracks"]),
                        bedtools.graph(input_bam, bed_graph_output, big_wig_output, "")
                    ], name="wiggle." + re.sub(".bedGraph", "", os.path.basename(bed_graph_output)))
                )

            # Generation of a bigWig from the methylation bedGraph
            methyl_directory = os.path.join("methylation_call", sample.name)
            candidate_input_files = [[os.path.join(methyl_directory, sample.name + ".sorted.dedup.bedGraph.gz")]]
            candidate_input_files.append([os.path.join(methyl_directory, sample.name + ".readset_sorted.dedup.bedGraph.gz")])
            candidate_input_files.append([os.path.join(methyl_directory, sample.name + ".sorted.bedGraph.gz")])
            [input_bed_graph] = self.select_input_files(candidate_input_files)
            output_wiggle = os.path.join("tracks", "bigWig", re.sub(".bam", ".bw", os.path.basename(input_bed_graph)))

            jobs.append(
                concat_jobs([
                    Job(command="mkdir -p " + methyl_directory),
                    ucsc.bedgraph_to_bigbwig(
                        input_bed_graph,
                        output_wiggle,
                        True
                    )
                ], name = "bismark_bigWig." + sample.name)
            )

        return jobs

    def methylation_profile(self):
        """
        Generation of a CpG methylation profile by combining both forward and reverse strand Cs.
        Also generating of all the methylatoin metrics : CpG stats, pUC19 CpG stats, lambda conversion rate, median CpG coverage, GC bias
        """

        jobs = []
        for sample in self.samples:
            methyl_directory = os.path.join("methylation_call", sample.name)

            candidate_input_files = [[os.path.join(methyl_directory, sample.name + ".sorted.dedup.CpG_report.txt.gz")]]
            candidate_input_files.append([os.path.join(methyl_directory, sample.name + ".readset_sorted.dedup.CpG_report.txt.gz")])
            candidate_input_files.append([os.path.join(methyl_directory, sample.name + ".sorted.CpG_report.txt.gz")])
            candidate_input_files.append([os.path.join(methyl_directory, sample.name + ".readset_sorted.CpG_report.txt.gz")])

            [cpG_input_file] = self.select_input_files(candidate_input_files)
            cpG_profile = re.sub(".CpG_report.txt.gz", ".CpG_profile.strand.combined.csv", cpG_input_file)

            # Generate CpG methylation profile
            job = methyl_profile.combine(
                cpG_input_file,
                cpG_profile
            )
            job.name = "methylation_profile." + sample.name
            jobs.append(job)

            # Generate stats for lambda, pUC19 and regular CpGs
            cg_stats_output = re.sub(".CpG_report.txt.gz", ".profile.cgstats.txt", cpG_input_file)
            lambda_stats_output = re.sub(".CpG_report.txt.gz", ".profile.lambda.conversion.rate.tsv", cpG_input_file)
            puc19_stats_output = re.sub(".CpG_report.txt.gz", ".profile.pUC19.txt", cpG_input_file)
            job = methyl_profile.cpg_stats(
                cpG_profile,
                cg_stats_output,
                lambda_stats_output,
                puc19_stats_output
            )
            job.name = "CpG_stats." + sample.name
            jobs.append(job)

            # Caluculate median & mean CpG coverage
            median_CpG_coverage = re.sub(".CpG_report.txt.gz", ".median_CpG_coverage.txt", cpG_input_file)
            job = methyl_profile.cpg_cov_stats(
                cpG_profile,
                median_CpG_coverage
            )
            job.name = "median_CpG_coverage." + sample.name
            jobs.append(job)

        return jobs

    def bis_snp(self):
        """
        SNP calling with BisSNP
        """

        jobs = []
        for sample in self.samples:
            alignment_directory = os.path.join("alignment", sample.name)

            candidate_input_files = [[os.path.join(alignment_directory, sample.name + ".sorted.dedup.bam")]]
            candidate_input_files.append([os.path.join(alignment_directory, sample.name + ".readset_sorted.dedup.bam")])
            candidate_input_files.append([os.path.join(alignment_directory, sample.name + ".sorted.bam")])
            [input_file] = self.select_input_files(candidate_input_files)

            variant_directory = os.path.join("variants", sample.name)
            cpg_output_file = os.path.join(variant_directory, sample.name + ".cpg.vcf")
            snp_output_file = os.path.join(variant_directory, sample.name + ".snp.vcf")

            jobs.append(
                concat_jobs([
                    Job(command="mkdir -p " + variant_directory),
                    bissnp.bisulfite_genotyper(
                        input_file,
                        cpg_output_file,
                        snp_output_file
                    )
                ], name="bissnp." + sample.name)
            )

        return jobs 

    @property
    def steps(self):
        return [
            self.picard_sam_to_fastq,
            self.trimmomatic,
            self.merge_trimmomatic_stats,
            self.bismark_align,
            self.picard_add_read_groups,    # step 5
            self.picard_merge_sam_files,
            self.bismark_dedup,
            self.metrics,
            self.verify_bam_id,
            self.methylation_call,          # step 10
            self.wiggle_tracks,
            self.methylation_profile,
            self.bis_snp                    # step 13
        ]

if __name__ == '__main__': 
    MethylSeq()
