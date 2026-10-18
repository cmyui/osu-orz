cmake_minimum_required(VERSION 3.18...3.31)
project(${SKBUILD_PROJECT_NAME} LANGUAGES C CXX)

find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module ${SKBUILD_SABI_COMPONENT})
find_package(nanobind CONFIG REQUIRED)

set(ORZ ${CMAKE_CURRENT_SOURCE_DIR}/extern/osu_replay_zip)

# the LZMA SDK decoder the codec reads replay data with
add_library(orz_lzma STATIC ${ORZ}/Lib/LzmaDec.c)
target_include_directories(orz_lzma PUBLIC ${ORZ}/Lib)
set_target_properties(orz_lzma PROPERTIES POSITION_INDEPENDENT_CODE ON)

nanobind_add_module(_core STABLE_ABI NB_STATIC src/osu_orz/_core.cpp)
target_compile_features(_core PRIVATE cxx_std_20)
target_include_directories(_core PRIVATE ${ORZ})
target_link_libraries(_core PRIVATE orz_lzma)

# files only decode where every build does its float maths exactly as written: no fused multiply-add contraction
# (which -march=native would allow) and no fast-math
target_compile_options(_core PRIVATE -ffp-contract=off -fno-fast-math)

install(TARGETS _core LIBRARY DESTINATION osu_orz)
